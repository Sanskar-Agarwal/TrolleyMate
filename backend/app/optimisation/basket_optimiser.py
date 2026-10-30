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
from app.services.build_control import checkpoint


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
        checkpoint()
        started = time.perf_counter()
        min_qty, max_qty, prefer = min_qty or {}, max_qty or {}, prefer or set()
        pool = [c for c in candidates if math.isfinite(c.price) and c.price > 0 and c.compliance != "violation"]
        if not pool:
            return OptimisationResult(False, message="No priced, compliant products to choose from.", requirements=req)

        available = {c.product.id for c in pool}
        for pid, minimum in min_qty.items():
            if minimum > 0 and pid not in available:
                return OptimisationResult(False, message="A required product is unavailable or excluded.", requirements=req)
        for pid in min_qty.keys() | max_qty.keys():
            lo, hi = min_qty.get(pid, 0), max_qty.get(pid)
            if any(isinstance(q, bool) or not isinstance(q, int) or q < 0 for q in (lo, hi) if q is not None):
                return OptimisationResult(False, message="Product quantities must be non-negative whole numbers.", requirements=req)
            if hi is not None and lo > hi:
                return OptimisationResult(False, message="Minimum quantity exceeds the maximum for a product.", requirements=req)

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
        for nutrient, minimum in req.extra_minimums.items():
            at_least([c.nutrient(nutrient) for c in pool], minimum)
        at_least([c.product.servings if c.role == "protein" else 0 for c in pool], req.protein_servings)
        at_least([c.product.servings if c.role == "carb" else 0 for c in pool], req.carb_servings)
        at_least([c.product.servings if c.is_breakfast and c.role is None else 0 for c in pool], req.breakfast_servings)
        # A breakfast recipe has two slots (e.g. oats + fruit). Cover both from breakfast-only foods,
        # since the meal plan saves bread and eggs for the lunches and dinners that need them.
        at_least([c.product.servings if c.is_breakfast_side and c.role is None else 0 for c in pool], 2 * req.breakfast_meals)
        # Bread and eggs can fill a dinner or a breakfast but not both: count the overlap once.
        if req.breakfast_meals:
            at_least([c.product.servings if c.role in ("protein", "carb") or c.is_breakfast_side else 0 for c in pool],
                     req.protein_servings + req.carb_servings + 2 * req.breakfast_meals)

        # Variety: no single food group (e.g. legumes, rice) may supply more than its share of a role.
        needs = {"protein": req.protein_servings, "carb": req.carb_servings, "veg": req.veg_serves}
        groups: dict[tuple[str, str], list[int]] = {}
        for i, c in enumerate(pool):
            if c.role and needs[c.role] > 4:
                groups.setdefault((c.role, c.product.substitution_group or c.product.sku), []).append(i)
        for (role, _), members in groups.items():
            cap = max(self.GROUP_SHARE[role] * needs[role], max(pool[i].role_units for i in members))
            # Variety is a soft rule: a quantity the shopper explicitly pinned may exceed it.
            cap = max(cap, sum(pool[i].role_units * min_qty.get(pool[i].product.id, 0) for i in members))
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
        checkpoint()
        elapsed = int((time.perf_counter() - started) * 1000)
        if result.x is None:
            reason = "timeout" if result.status == 1 else None if result.status == 2 else "solver_error"
            message = ("The search timed out before finding a valid basket." if reason == "timeout" else
                       "The solver could not complete the search." if reason else "No basket satisfies every constraint.")
            return OptimisationResult(False, message=message, solver_ms=elapsed, requirements=req, failure_reason=reason)

        # A time-limited solve can return a valid incumbent. Check the integer
        # basket against every hard constraint before exposing it as a result.
        quantities = np.rint(result.x)
        valid = np.all(np.isfinite(quantities)) and np.all(quantities >= lower) and np.all(quantities <= upper)
        if rows:
            values = np.array(rows) @ quantities
            valid = valid and np.all(values >= np.array(lbs) - 1e-7) and np.all(values <= np.array(ubs) + 1e-7)
        if not valid:
            return OptimisationResult(False, message="The solver returned an unverified candidate.", solver_ms=elapsed,
                                      requirements=req, failure_reason="solver_error")

        items = [(c, int(q)) for c, q in zip(pool, quantities, strict=True) if q > 0]
        total = round(sum(c.price * q for c, q in items), 2)
        nutrition = {k: round(sum(c.nutrient(k) * q for c, q in items), 1) for k in NUTRIENTS}
        metrics = {
            "surplus_servings": round(
                sum(c.role_units * q for c, q in items if c.role) - (req.protein_servings + req.carb_servings + req.veg_serves), 1
            ),
            "prep_minutes": round(sum(c.product.prep_minutes_per_serving * c.product.servings * q for c, q in items)),
            "objective": round(float(cost @ quantities), 3),
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
