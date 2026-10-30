from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache

from app.domain.basket_products import Product
from app.domain.pricing import Retailer
from app.domain.requests_constraints import ConstraintSet
from app.services.meal_schedule import meal_schedule

ROLE_CATEGORIES = ("protein", "carb", "veg")
BREAKFAST_SIDE_TAGS = frozenset({"breakfast", "fruit", "dairy", "milk_drink", "yoghurt"})


@lru_cache
def main_recipe_tags() -> frozenset[str]:
    """Every product tag some lunch/dinner recipe can use (seed/recipes.json)."""
    from app.seed import load_recipes

    return frozenset(t for r in load_recipes() if r["meal_type"] == "main" for need in r["needs"] for t in need)
NUTRIENTS = ("kcal", "protein_g", "carbs_g", "fat_g", "fibre_g", "veg_serves")
_NUTRIENT_ALIASES = {
    "protein": "protein_g", "calories": "kcal", "energy": "kcal", "carbs": "carbs_g", "carbohydrates": "carbs_g",
    "carbs_g": "carbs_g", "fat": "fat_g", "fibre": "fibre_g", "fiber": "fibre_g", "fiber_g": "fibre_g",
    "veg": "veg_serves", "vegetables": "veg_serves", "veg_serves": "veg_serves",
}


def normalise_nutrient(name: str) -> str | None:
    """Map a target's nutrient name onto a catalogue nutrition field, or None if we can't check it."""
    key = name.strip().lower().replace(" ", "_")
    key = _NUTRIENT_ALIASES.get(key, key)
    return key if key in NUTRIENTS else None


@dataclass
class Candidate:
    """One product the solver may buy, at the retailer currently offering it cheapest."""

    product: Product
    retailer: Retailer
    price: float
    quote_id: int | None = None
    unit_price: float | None = None
    unit_basis: str = ""
    compliance: str = "compliant"  # compliant | uncertain
    on_special: bool = False

    @property
    def role(self) -> str | None:
        """protein / carb / veg for lunch-and-dinner cover — only if some main recipe can cook with it,
        so e.g. breakfast oats never stand in for the rice or pasta a dinner needs."""
        if self.product.category not in ROLE_CATEGORIES:
            return None
        return self.product.category if (set(self.product.tags) | {self.product.category}) & main_recipe_tags() else None

    @property
    def is_breakfast(self) -> bool:
        return "breakfast" in self.product.tags

    @property
    def is_breakfast_side(self) -> bool:
        """Fills either slot of a breakfast recipe (the item itself, or fruit/dairy alongside it)."""
        return bool((set(self.product.tags) | {self.product.category}) & BREAKFAST_SIDE_TAGS)

    def nutrient(self, key: str) -> float:
        val = self.product.nutrition.get(key, 0.0)
        return float(val) if val is not None else 0.0

    @property
    def role_units(self) -> float:
        """How much this pack contributes to its role requirement."""
        if self.role == "veg":
            return self.nutrient("veg_serves")
        return float(self.product.servings)

    @property
    def price_per_serving(self) -> float:
        return self.price / max(self.product.servings, 1)


@dataclass
class Requirements:
    """What the basket must cover, derived from a confirmed ConstraintSet."""

    household_size: int
    days: int
    meals_per_day: float
    budget: float | None
    person_meals: int
    main_meals: int
    breakfast_meals: int
    kcal: float
    protein_g: float
    veg_serves: float
    protein_servings: float
    carb_servings: float
    breakfast_servings: float
    # Shopper targets for nutrients without a default requirement (e.g. fibre_g), as basket totals.
    extra_minimums: dict[str, float] = field(default_factory=dict)
    meal_count: int | None = None  # exact scheduled meals per person after a confirmed trade-off
    portions: float = 0.0  # adult-equivalent eaters; 0 means "same as household_size" (older saved baskets)

    KCAL_PER_MEAL = 550
    PROTEIN_PER_MAIN = 22
    VEG_PER_MAIN = 2.0

    @classmethod
    def from_constraints(cls, cs: ConstraintSet, *, days: int | None = None, budget: float | None = ...) -> Requirements:
        p = cs.payload
        size = int(p.get("household_size") or 1)
        # Adult-equivalent eaters (a child eats ~0.6 of an adult serve); intake sets it from the profile.
        portions = float(p.get("portions") or size)
        d = int(days if days is not None else p.get("days") or 7)
        mpd = float(p.get("meals_per_day") or 2)
        count = p.get("meal_count")
        schedule = meal_schedule(d, mpd, count)
        breakfast = math.ceil(portions * sum("Breakfast" in slots for slots in schedule) - 1e-9)
        # Round each role up independently: rounding breakfast must never take a
        # fractional child's lunch/dinner portion away from the main requirement.
        main = math.ceil(portions * sum(sum(slot != "Breakfast" for slot in slots) for slots in schedule) - 1e-9)
        person_meals = main + breakfast
        defaults = {"kcal": cls.KCAL_PER_MEAL * person_meals, "protein_g": cls.PROTEIN_PER_MAIN * main,
                    "veg_serves": cls.VEG_PER_MAIN * main}
        extra: dict[str, float] = {}
        for t in p.get("nutritional_targets", []):
            nutrient = normalise_nutrient(t["nutrient"])
            if nutrient is None:
                continue  # intake flags targets we can't check; they never reach a confirmed set
            total = float(t["minimum_per_day"]) * size * d
            if nutrient in defaults:
                defaults[nutrient] = max(defaults[nutrient], total)
            else:
                extra[nutrient] = max(extra.get(nutrient, 0.0), total)
        return cls(
            household_size=size, days=d, meals_per_day=mpd,
            budget=(p.get("budget") if budget is ... else budget),
            person_meals=person_meals, main_meals=main, breakfast_meals=breakfast,
            kcal=defaults["kcal"], protein_g=defaults["protein_g"],
            veg_serves=defaults["veg_serves"],
            protein_servings=main, carb_servings=main,
            breakfast_servings=math.ceil(1.6 * breakfast),
            extra_minimums=extra,
            meal_count=count,
            portions=portions,
        )

    @property
    def scheduled_meals(self) -> int:
        return sum(map(len, meal_schedule(self.days, self.meals_per_day, self.meal_count)))

    def as_dict(self) -> dict:
        return {**{k: getattr(self, k) for k in self.__dataclass_fields__}, "scheduled_meals": self.scheduled_meals}


@dataclass
class OptimisationResult:
    feasible: bool
    items: list[tuple[Candidate, int]] = field(default_factory=list)
    total: float = 0.0
    nutrition: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    message: str = ""
    solver_ms: int = 0
    requirements: Requirements | None = None
    failure_reason: str | None = None  # timeout | solver_error; None means proven/structural infeasibility

    @property
    def timed_out(self) -> bool:
        """The solver hit its time limit: no answer, which is not proof of infeasibility (UC-02 ext 2b/3b)."""
        return self.failure_reason == "timeout"
