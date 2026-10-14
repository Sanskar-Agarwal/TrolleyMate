"""BasketOptimiser — deterministic integer-linear-programming solver (Section 4.1).

Selecting the best valid basket from a candidate set is "a constrained
optimisation problem with a single correct answer", so no LLM is involved here.
Solved with SciPy's MILP interface (HiGHS solver).

    variables  x_c ∈ {0..ub_c}   packs of candidate c
    minimise   Σ coef_c · x_c     (coef from the OptimisationStrategy)
    subject to Σ price_c · x_c ≤ budget
               Σ kcal, protein, veg serves ≥ requirements
               Σ servings per role (protein, carb, breakfast) ≥ requirements
               ub_c keeps any single product to about half of its role (variety)
"""

from __future__ import annotations

import math
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from app.core.config import get_settings
from app.optimisation.strategies import OptimisationStrategy
from app.optimisation.types import NUTRIENTS, Candidate, OptimisationResult, Requirements


class BasketOptimiser:
    # Max share of a role's requirement any one food group (substitution_group) may supply.
    GROUP_SHARE = {"protein": 0.4, "carb": 0.5, "veg": 0.4}
    PRODUCT_SHARE = 0.35

    def __init__(self, solver_timeout_ms: int | None = None):
        self.solver_timeout_ms = solver_timeout_ms or get_settings().solver_timeout_ms

    def solve(
        self,
        req: Requirements,
        strategy: OptimisationStrategy,
        candidates: list[Candidate],
        *,
        min_qty: dict[int, int] | None = None,
        max_qty: dict[int, int] | None = None,
        prefer: set[int] | None = None,
        enforce_budget: bool = True,
    ) -> OptimisationResult:
        """min_qty / max_qty pin product quantities (from conversational edits);
        `prefer` nudges the solver to keep current items so an edit doesn't reshuffle everything."""
        started = time.perf_counter()
        min_qty, max_qty, prefer = min_qty or {}, max_qty or {}, prefer or set()
        pool = [c for c in candidates if c.price > 0]
        if not pool:
            return OptimisationResult(False, message="No priced, compliant products to choose from.", requirements=req)

        strategy.prepare(pool)
        req = strategy.adjust(req)
        n = len(pool)
        coefficients = []
        for c in pool:
            k = strategy.coefficient(c, req)
            if c.product.id in prefer:
                k -= 0.08 * abs(k) + 0.01
            if c.compliance == "uncertain":
                k += 0.1 * abs(k) + 0.01  # prefer certain items when otherwise equal
            coefficients.append(k)
        cost = np.array(coefficients)
        prices = np.array([c.price for c in pool])

        rows, lbs, ubs = [], [], []

        def at_least(values: list[float], minimum: float) -> None:
            if minimum > 0:
                rows.append(values)
                lbs.append(minimum)
                ubs.append(np.inf)

        if enforce_budget and req.budget is not None:
            rows.append(list(prices))
            lbs.append(0)
            ubs.append(float(req.budget))
        at_least([c.nutrient("kcal") for c in pool], req.kcal)
        at_least([c.nutrient("protein_g") for c in pool], req.protein_g)
        at_least([c.nutrient("veg_serves") for c in pool], req.veg_serves)
        at_least([c.product.servings if c.role == "protein" else 0 for c in pool], req.protein_servings)
        at_least([c.product.servings if c.role == "carb" else 0 for c in pool], req.carb_servings)
        at_least([c.product.servings if c.is_breakfast else 0 for c in pool], req.breakfast_servings)

        # Variety: no single food group (e.g. legumes, rice) may supply more than its share of a role.
        needs = {"protein": req.protein_servings, "carb": req.carb_servings, "veg": req.veg_serves}
        groups: dict[tuple[str, str], list[int]] = {}
        for i, c in enumerate(pool):
            if c.role and needs[c.role] > 4:
                groups.setdefault((c.role, c.product.substitution_group or c.product.sku), []).append(i)
        for (role, _), members in groups.items():
            cap = max(self.GROUP_SHARE[role] * needs[role], max(pool[i].role_units for i in members))
            rows.append([pool[i].role_units if i in members else 0 for i in range(n)])
            lbs.append(0)
            ubs.append(cap)

        lower = np.array([float(min_qty.get(c.product.id, 0)) for c in pool])
        upper = np.array(
            [
                max(float(max_qty[c.product.id]) if c.product.id in max_qty else self._upper_bound(c, req), lower[i])
                for i, c in enumerate(pool)
            ]
        )

        result = milp(
            c=cost,
            constraints=[LinearConstraint(np.array(rows), np.array(lbs), np.array(ubs))] if rows else [],
            integrality=np.ones(n),
            bounds=Bounds(lower, upper),
            options={"time_limit": self.solver_timeout_ms / 1000, "disp": False},
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        if result.x is None:
            message = "Timed out before finding a basket." if result.status == 1 else "No basket satisfies every constraint."
            return OptimisationResult(False, message=message, solver_ms=elapsed, requirements=req)

        items = [(c, int(round(q))) for c, q in zip(pool, result.x, strict=True) if round(q) > 0]
        total = round(sum(c.price * q for c, q in items), 2)
        nutrition = {k: round(sum(c.nutrient(k) * q for c, q in items), 1) for k in NUTRIENTS}
        metrics = {
            "surplus_servings": round(
                sum(c.role_units * q for c, q in items if c.role) - (req.protein_servings + req.carb_servings + req.veg_serves), 1
            ),
            "prep_minutes": round(sum(c.product.prep_minutes_per_serving * c.product.servings * q for c, q in items)),
            "objective": round(float(result.fun), 3),
        }
        return OptimisationResult(True, items, total, nutrition, metrics, solver_ms=elapsed, requirements=req)

    def is_feasible(self, req: Requirements, strategy: OptimisationStrategy, candidates: list[Candidate]) -> bool:
        return self.solve(req, strategy, candidates).feasible

    @classmethod
    def _upper_bound(cls, c: Candidate, req: Requirements) -> float:
        if c.role == "protein":
            need = req.protein_servings
        elif c.role == "carb":
            need = req.carb_servings
        elif c.role == "veg":
            need = req.veg_serves
        elif c.is_breakfast:
            need = req.breakfast_servings
        else:
            return 2.0
        if need <= 4:
            return float(max(1, math.ceil(need / max(c.role_units, 1))))
        return float(max(1, math.ceil(cls.PRODUCT_SHARE * need / max(c.role_units, 1))))
