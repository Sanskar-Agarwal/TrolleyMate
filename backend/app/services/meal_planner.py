"""Deterministic meal planner (1.2.3 / UC-08). Recipes come only from the basket.

Each meal slot picks a recipe whose required slots can be filled from what's left
in the basket, preferring recipes that reuse already-opened packs and that use
perishables early. Nothing is added to the basket to make a recipe work; meals
that can't be planned are reported with the items they would need.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from app.domain import Basket
from app.seed import load_recipes
from app.services.meal_schedule import meal_schedule


@dataclass
class Stock:
    item_id: int
    name: str
    tags: set[str]
    remaining: float
    shelf_life: int
    perishable: bool
    opened: bool = False


def plan(basket: Basket, household_size: int, days: int, meals_per_day: float) -> dict:
    recipes = load_recipes()
    stock = [
        # Category is added as a tag so generic recipes ("protein", "carb", "veg") can match.
        Stock(i.id, i.product.name, set(i.product.tags) | {i.product.category}, float(i.product.servings * i.quantity),
              i.product.shelf_life_days, i.product.perishable)
        for i in basket.items if not i.withheld
    ]
    schedule = meal_schedule(days, meals_per_day)
    requested = sum(len(slots) for slots in schedule)
    used_count: dict[str, int] = {}
    reused: set[str] = set()
    plan_days, missing = [], []

    for day, slots in enumerate(schedule, start=1):
        meals = []
        available = [s for s in stock if not s.perishable or day <= s.shelf_life]
        for slot in slots:
            meal_type = "breakfast" if slot == "Breakfast" else "main"
            options = [r for r in recipes if r["meal_type"] == meal_type]
            best, best_score, best_alloc = None, None, None
            for r in options:
                alloc = _allocate(r["needs"], available, household_size)
                if alloc is None:
                    continue
                score = (
                    sum(2 for s in alloc if s.opened)
                    + sum(1.5 for s in alloc if s.perishable and s.shelf_life <= 7 and day <= 3)
                    - 3 * used_count.get(r["id"], 0)
                    - (2.5 if r.get("generic") else 0)  # named recipes first; generic ones fill gaps
                )
                if best_score is None or score > best_score:
                    best, best_score, best_alloc = r, score, alloc
            if best is None:
                need = _closest_missing(options, available, household_size)
                missing.append({"day": day, "slot": slot, **need})
                meals.append({"slot": slot, "recipe": None, "missing": need["missing_tags"]})
                continue
            for s in best_alloc:
                if s.opened:
                    reused.add(s.name)
                s.remaining -= household_size
                s.opened = True
            extras = []
            for tags in best.get("optional", []):
                extra = _allocate([tags], available, household_size)
                if extra:
                    ingredient = extra[0]
                    ingredient.remaining -= household_size
                    if ingredient.opened:
                        reused.add(ingredient.name)
                    ingredient.opened = True
                    extras.append(ingredient.name)
            used_count[best["id"]] = used_count.get(best["id"], 0) + 1
            meals.append({
                "slot": slot, "recipe": best["name"], "recipe_id": best["id"], "minutes": best["minutes"],
                "uses": [s.name for s in best_alloc], "optional": extras, "servings": household_size,
            })
        plan_days.append({"day": day, "meals": meals})

    leftovers = [{"name": s.name, "servings_left": round(s.remaining, 1)} for s in stock if s.remaining >= 1 and (not s.perishable or s.shelf_life >= days)]
    return {
        "days": plan_days,
        "requested": requested,
        "planned": requested - len(missing),
        "missing": missing,
        "reused": sorted(reused),
        "leftovers": leftovers,
        "expired_unused": [{"name": s.name, "servings_left": round(s.remaining, 1)} for s in stock
                           if s.perishable and s.shelf_life < days and s.remaining >= 1],
        "perishable_first": [s.name for s in sorted(stock, key=lambda s: s.shelf_life) if s.perishable][:3],
        "assumed_at_home": ["salt", "pepper", "cooking oil"],
    }


def _allocate(needs: list[list[str]], stock: list[Stock], servings: int) -> list[Stock] | None:
    # Reserve stock while searching. A flexible ingredient must not starve a later,
    # more specific slot, and a product cannot supply more servings than it contains.
    chosen: list[Stock] = []

    def fill(index: int) -> bool:
        if index == len(needs):
            return True
        choices = [s for s in stock if s.tags & set(needs[index])
                   and s.remaining - chosen.count(s) * servings >= servings]
        choices.sort(key=lambda s: (not s.opened, s.shelf_life, -s.remaining))
        for item in choices:
            chosen.append(item)
            if fill(index + 1):
                return True
            chosen.pop()
        return False

    return list(chosen) if fill(0) else None


def _closest_missing(options: list[dict], stock: list[Stock], servings: int) -> dict:
    if not options:
        return {"suggested_recipe": "No matching recipe", "missing_tags": ["a suitable recipe"]}
    best = None
    for recipe in options:
        needs = recipe["needs"]
        for missing_count in range(len(needs) + 1):
            match = None
            for missing in combinations(range(len(needs)), missing_count):
                keep = [tags for i, tags in enumerate(needs) if i not in missing]
                if _allocate(keep, stock, servings) is not None:
                    match = list(missing)
                    break
            if match is not None:
                if best is None or len(match) < len(best[1]):
                    best = (recipe, match)
                break
    recipe, gaps = best
    return {"suggested_recipe": recipe["name"],
            "missing_tags": [recipe["needs"][i][0].replace("_", " ") for i in gaps]}
