"""Deterministic meal planner (1.2.3 / UC-08). Recipes come only from the basket.

Each meal slot picks a recipe whose required slots can be filled from what's left
in the basket, preferring recipes that reuse already-opened packs and that use
perishables early. Nothing is added to the basket to make a recipe work; meals
that can't be planned are reported with the items they would need.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain import Basket
from app.seed import load_recipes

SLOT_NAMES = {1: ["Dinner"], 2: ["Lunch", "Dinner"], 3: ["Breakfast", "Lunch", "Dinner"]}


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
    slots = SLOT_NAMES.get(int(min(max(round(meals_per_day), 1), 3)))
    used_count: dict[str, int] = {}
    reused: set[str] = set()
    plan_days, missing = [], []

    for day in range(1, days + 1):
        meals = []
        for slot in slots:
            meal_type = "breakfast" if slot == "Breakfast" else "main"
            options = [r for r in recipes if r["meal_type"] == meal_type]
            best, best_score, best_alloc = None, None, None
            for r in options:
                alloc = _allocate(r["needs"], stock, household_size)
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
                need = _closest_missing(options, stock, household_size)
                missing.append({"day": day, "slot": slot, **need})
                meals.append({"slot": slot, "recipe": None, "missing": need["missing_tags"]})
                continue
            for s in best_alloc:
                if s.opened:
                    reused.add(s.name)
                s.remaining -= household_size
                s.opened = True
            extras = [s.name for opt in best.get("optional", []) for s in stock if s.tags & set(opt) and s.remaining > 0][:2]
            used_count[best["id"]] = used_count.get(best["id"], 0) + 1
            meals.append({
                "slot": slot, "recipe": best["name"], "recipe_id": best["id"], "minutes": best["minutes"],
                "uses": [s.name for s in best_alloc], "optional": extras, "servings": household_size,
            })
        plan_days.append({"day": day, "meals": meals})

    leftovers = [{"name": s.name, "servings_left": round(s.remaining, 1)} for s in stock if s.remaining >= 1]
    return {
        "days": plan_days,
        "requested": days * len(slots),
        "planned": days * len(slots) - len(missing),
        "missing": missing,
        "reused": sorted(reused),
        "leftovers": leftovers,
        "perishable_first": [s.name for s in sorted(stock, key=lambda s: s.shelf_life) if s.perishable][:3],
        "assumed_at_home": ["salt", "pepper", "cooking oil"],
    }


def _allocate(needs: list[list[str]], stock: list[Stock], servings: int) -> list[Stock] | None:
    alloc: list[Stock] = []
    for tags in needs:
        choices = [s for s in stock if s.tags & set(tags) and s.remaining - alloc.count(s) * servings >= servings]
        if not choices:
            return None
        choices.sort(key=lambda s: (not s.opened, s.shelf_life, -s.remaining))
        alloc.append(choices[0])
    return alloc


def _closest_missing(options: list[dict], stock: list[Stock], servings: int) -> dict:
    best = None
    for r in options:
        missing = [tags for tags in r["needs"] if not any(s.tags & set(tags) and s.remaining >= servings for s in stock)]
        if best is None or len(missing) < len(best[1]):
            best = (r, missing)
    recipe, gaps = best
    return {"suggested_recipe": recipe["name"], "missing_tags": [t[0].replace("_", " ") for t in gaps]}
