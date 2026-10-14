"""OptimisationStrategy «interface» and its five realisations (1.2.2 goal selector).

Each strategy turns a candidate into one linear objective coefficient (the solver
minimises Σ coefficient × packs). Allergen/dietary rules never appear here — they
are enforced before the solver sees a candidate, so no goal can trade them away.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.enums import OptimisationGoal
from app.optimisation.types import Candidate, Requirements

COST_TIEBREAK = 0.05


class OptimisationStrategy(ABC):
    goal: OptimisationGoal
    label: str

    def prepare(self, candidates: list[Candidate]) -> None:
        """Hook for strategies that normalise across the candidate set."""

    def adjust(self, req: Requirements) -> Requirements:
        """Hook for strategies that raise the bar on requirements (never lower safety)."""
        return req

    @abstractmethod
    def coefficient(self, c: Candidate, req: Requirements) -> float: ...

    @abstractmethod
    def item_reason(self, c: Candidate) -> str: ...

    def score(self, items: list[tuple[Candidate, int]]) -> float:
        """Higher is better; shown next to the basket."""
        return -sum(self.coefficient(c, None) * q for c, q in items)  # type: ignore[arg-type]


def _nutrition_value(c: Candidate) -> float:
    return c.nutrient("protein_g") * 0.04 + c.nutrient("fibre_g") * 0.08 + c.nutrient("veg_serves") * 0.5


def _waste(c: Candidate) -> float:
    return c.role_units * (1.6 if c.product.perishable else 1.0)


def _prep(c: Candidate) -> float:
    return c.product.prep_minutes_per_serving * c.product.servings


class LowestCost(OptimisationStrategy):
    goal = OptimisationGoal.lowest_cost
    label = "Lowest cost"

    def coefficient(self, c: Candidate, req: Requirements) -> float:
        return c.price

    def item_reason(self, c: Candidate) -> str:
        return f"Lowest price per serving for its role (${c.price_per_serving:.2f}/serving at {c.retailer.name})"


class BestNutrition(OptimisationStrategy):
    """Raises the vegetable/protein bar, then buys the most nutrient-dense way to meet it.
    Coefficients stay positive so the solver never buys extra food just to score points."""

    goal = OptimisationGoal.best_nutrition
    label = "Best nutrition"

    def __init__(self) -> None:
        self._max_density = 1.0

    def prepare(self, candidates: list[Candidate]) -> None:
        if candidates:
            self._max_density = max(_nutrition_value(c) / c.price for c in candidates) or 1.0

    def adjust(self, req: Requirements) -> Requirements:
        from dataclasses import replace

        return replace(req, veg_serves=req.veg_serves * 1.6, protein_g=req.protein_g * 1.1)

    def coefficient(self, c: Candidate, req: Requirements) -> float:
        density = _nutrition_value(c) / c.price / self._max_density
        return c.price * (1.0 - 0.6 * density)

    def item_reason(self, c: Candidate) -> str:
        n = c.product.nutrition
        return f"High nutrient density ({n.get('protein_g', 0):.0f} g protein, {n.get('fibre_g', 0):.0f} g fibre per pack)"


class LeastWaste(OptimisationStrategy):
    goal = OptimisationGoal.least_waste
    label = "Least food waste"

    def coefficient(self, c: Candidate, req: Requirements) -> float:
        return _waste(c) + COST_TIEBREAK * c.price

    def item_reason(self, c: Candidate) -> str:
        life = "keeps well" if not c.product.perishable else f"use within {c.product.shelf_life_days} days"
        return f"Pack size fits your meal count with little left over ({life})"


class FastestToCook(OptimisationStrategy):
    goal = OptimisationGoal.fastest_cook
    label = "Shortest cooking time"

    def coefficient(self, c: Candidate, req: Requirements) -> float:
        return _prep(c) + COST_TIEBREAK * c.price

    def item_reason(self, c: Candidate) -> str:
        return f"Quick to prepare (about {c.product.prep_minutes_per_serving:g} min per serving)"


class Balanced(OptimisationStrategy):
    goal = OptimisationGoal.balanced
    label = "Balanced"

    def __init__(self) -> None:
        self._max = {"price": 1.0, "waste": 1.0, "prep": 1.0, "nutrition": 1.0}

    def prepare(self, candidates: list[Candidate]) -> None:
        if candidates:
            self._max = {
                "price": max(c.price for c in candidates) or 1.0,
                "waste": max(_waste(c) for c in candidates) or 1.0,
                "prep": max(_prep(c) for c in candidates) or 1.0,
                "nutrition": max(_nutrition_value(c) for c in candidates) or 1.0,
            }

    def coefficient(self, c: Candidate, req: Requirements) -> float:
        m = self._max
        return (
            0.55 * c.price / m["price"]
            + 0.2 * _waste(c) / m["waste"]
            + 0.15 * _prep(c) / m["prep"]
            + 0.1 * (1 - _nutrition_value(c) / m["nutrition"])
        )

    def item_reason(self, c: Candidate) -> str:
        return f"Good balance of price (${c.price_per_serving:.2f}/serving), nutrition and prep time"


STRATEGIES: dict[str, type[OptimisationStrategy]] = {
    s.goal: s for s in (LowestCost, BestNutrition, LeastWaste, FastestToCook, Balanced)
}


def strategy_for(goal: str) -> OptimisationStrategy:
    return STRATEGIES.get(goal, Balanced)()
