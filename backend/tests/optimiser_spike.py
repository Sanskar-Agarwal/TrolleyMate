"""P01 solver spike: run the deterministic small-catalogue fixtures through BasketOptimiser.

    python -m tests.optimiser_spike          # from backend/, prints the fixture results

No database or LLM is involved: products, the retailer and candidates are built
in memory from tests/fixtures/optimiser_cases.json. The contract these cases pin
down is docs/OPTIMISER_CONTRACT.md.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

from app.domain import Product, Retailer
from app.optimisation import STRATEGIES, BasketOptimiser, Requirements, strategy_for
from app.optimisation.strategies import LowestCost
from app.optimisation.types import Candidate, OptimisationResult

FIXTURES = Path(__file__).parent / "fixtures" / "optimiser_cases.json"


@dataclass
class Case:
    id: str
    goal: str
    req: Requirements
    candidates: list[Candidate]
    expect: dict


@dataclass
class CaseResult:
    case: Case
    goal: str
    result: OptimisationResult
    min_budget: float | None = None  # uncapped Lowest Cost total under the goal's own requirements

    @property
    def items(self) -> dict[str, int]:
        return {c.product.sku: q for c, q in self.result.items}


def load_cases() -> list[Case]:
    data = json.loads(FIXTURES.read_text())
    retailer = Retailer(**data["retailer"])
    candidates = []
    for p in data["products"]:
        fields = {k: v for k, v in p.items() if k != "price"}
        product = Product(tags=[], may_contain=[], shelf_life_days=7, data_complete=True, pack_size=500, unit="g", **fields)
        candidates.append(Candidate(product, retailer, p["price"], quote_id=p["id"]))
    cases = []
    for c in data["cases"]:
        req = Requirements(budget=c["budget"], **data["requirements"])
        excluded = set(c.get("exclude", []))
        pool = [cand for cand in candidates if cand.product.sku not in excluded]
        cases.append(Case(c["id"], c["goal"], req, pool, c["expect"]))
    return cases


def run_case(case: Case, goal: str | None = None) -> CaseResult:
    goal = goal or case.goal
    strategy = strategy_for(goal)
    optimiser = BasketOptimiser()
    result = optimiser.solve(case.req, strategy, case.candidates)
    min_budget = None
    if not result.feasible and not result.timed_out:
        # Same calculation UC-03 uses: price the goal's own bar the cheapest way, without a budget cap.
        cheapest = optimiser.solve(strategy_for(goal).adjust(case.req), LowestCost(), case.candidates, enforce_budget=False)
        if cheapest.feasible:
            min_budget = math.ceil(cheapest.total * 100) / 100
    return CaseResult(case, goal, result, min_budget)


def run_all() -> list[CaseResult]:
    results = []
    for case in load_cases():
        goals = list(STRATEGIES) if case.goal == "*" else [case.goal]
        results.extend(run_case(case, g) for g in goals)
    return results


def resolve_at(case: Case, goal: str, budget: float) -> OptimisationResult:
    return BasketOptimiser().solve(replace(case.req, budget=budget), strategy_for(goal), case.candidates)


def main() -> None:
    header = f"{'case':34} {'goal':15} {'feasible':8} {'timeout':7} {'total':>7} {'min $':>7} {'ms':>4}  items"
    print(header)
    print("-" * len(header))
    for r in run_all():
        total = f"{r.result.total:.2f}" if r.result.feasible else "-"
        min_budget = f"{r.min_budget:.2f}" if r.min_budget is not None else "-"
        items = ", ".join(f"{sku}×{q}" for sku, q in sorted(r.items.items())) or r.result.message
        print(f"{r.case.id:34} {r.goal:15} {str(r.result.feasible):8} {str(r.result.timed_out):7} {total:>7} {min_budget:>7} "
              f"{r.result.solver_ms:>4}  {items}")


if __name__ == "__main__":
    main()
