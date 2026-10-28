"""Deterministic, quantity-limited meal planning from an accepted basket.

Required ingredients are reserved before optional extras. Ingredient slots can
combine partial packs, and recipe time/perishability drive the matching goals.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from itertools import combinations

from app.domain import Basket
from app.seed import load_recipes
from app.services.meal_schedule import meal_schedule

EPSILON = 1e-8


@dataclass
class Stock:
    item_id: int
    name: str
    tags: set[str]
    remaining: float
    shelf_life: int
    perishable: bool
    opened: bool = False


@dataclass
class Allocation:
    stock: Stock
    servings: float


def plan(basket: Basket, household_size: int, days: int, meals_per_day: float, portions: float | None = None) -> dict:
    """One meal uses `portions` adult-equivalent serves; head count is the legacy default."""
    serve = float(household_size if portions is None else portions)
    if not math.isfinite(serve) or serve <= 0:
        raise ValueError("Household portions must be a positive number.")
    goal = getattr(basket, "goal", None) or "balanced"
    recipes = load_recipes()
    stock = [
        Stock(i.id, i.product.name, set(i.product.tags) | {i.product.category}, float(i.product.servings * i.quantity),
              i.product.shelf_life_days, i.product.perishable)
        for i in basket.items if not i.withheld
    ]
    schedule = meal_schedule(days, meals_per_day)
    main_tags = frozenset(t for r in recipes if r["meal_type"] == "main" for need in r["needs"] for t in need)
    requested = sum(len(slots) for slots in schedule)
    used_count: dict[str, int] = {}
    used_in: dict[int, set[tuple[int, str]]] = {}
    optional_jobs = []
    plan_days, missing = [], []

    def consume(alloc: list[Allocation], meal: dict, day: int) -> None:
        quantities = {i["name"]: i["servings"] for i in meal["ingredients"]}
        for a in alloc:
            a.stock.remaining = max(0.0, a.stock.remaining - a.servings)
            a.stock.opened = True
            used_in.setdefault(a.stock.item_id, set()).add((day, meal["slot"]))
            quantities[a.stock.name] = quantities.get(a.stock.name, 0) + a.servings
        meal["ingredients"] = [{"name": name, "servings": round(amount, 3)} for name, amount in quantities.items()]

    for day, slots in enumerate(schedule, start=1):
        meals = []
        available = [s for s in stock if not s.perishable or day <= s.shelf_life]
        for slot in slots:
            meal_type = "breakfast" if slot == "Breakfast" else "main"
            options = [r for r in recipes if r["meal_type"] == meal_type]
            best, best_score, best_alloc = None, None, None
            save = main_tags if meal_type == "breakfast" else frozenset()
            for recipe in options:
                alloc = _allocate(recipe["needs"], available, serve, save)
                if alloc is None:
                    continue
                score = (
                    sum(2 for a in alloc if a.stock.opened)
                    + sum(1.5 * max(0, 4 - (a.stock.shelf_life - day)) for a in alloc if a.stock.perishable)
                    - 3 * used_count.get(recipe["id"], 0)
                    - (2.5 if recipe.get("generic") else 0)
                    - sum(10 for a in alloc if a.stock.tags & save)
                )
                # Recipe minutes describe one household batch, not minutes per eater.
                if goal == "fastest_cook":
                    rank = (-recipe["minutes"], score)
                elif goal == "least_waste":
                    urgency = sum(a.servings / max(1, a.stock.shelf_life - day + 1)
                                  for a in alloc if a.stock.perishable)
                    rank = (urgency, score - 0.05 * recipe["minutes"])
                else:
                    rank = (score - 0.05 * recipe["minutes"], 0)
                if best_score is None or rank > best_score:
                    best, best_score, best_alloc = recipe, rank, alloc
            if best is None:
                need = _closest_missing(options, available, serve)
                missing.append({"day": day, "slot": slot, **need})
                meals.append({"slot": slot, "recipe": None, "missing": need["missing_tags"]})
                continue
            meal = {
                "slot": slot, "recipe": best["name"], "recipe_id": best["id"], "minutes": best["minutes"],
                "uses": list(dict.fromkeys(a.stock.name for a in best_alloc)), "optional": [],
                "servings": household_size, "ingredients": [],
            }
            consume(best_alloc, meal, day)
            optional_jobs.append((day, meal, best.get("optional", [])))
            used_count[best["id"]] = used_count.get(best["id"], 0) + 1
            meals.append(meal)
        plan_days.append({"day": day, "meals": meals})

    # Extras may use only stock left after every required meal has been reserved.
    for day, meal, optional in optional_jobs:
        available = [s for s in stock if not s.perishable or day <= s.shelf_life]
        for tags in optional:
            alloc = _allocate([tags], available, serve)
            if alloc:
                consume(alloc, meal, day)
                meal["optional"].extend(a.stock.name for a in alloc if a.stock.name not in meal["optional"])

    def remaining(s: Stock) -> dict:
        return {"name": s.name, "servings_left": round(s.remaining, 3)}

    return {
        "days": plan_days,
        "goal": goal,
        "portions_per_meal": serve,
        "total_minutes": sum(m.get("minutes", 0) for d in plan_days for m in d["meals"]),
        "requested": requested,
        "planned": requested - len(missing),
        "missing": missing,
        "reused": sorted({s.name for s in stock if len(used_in.get(s.item_id, set())) > 1}),
        "leftovers": [remaining(s) for s in stock if s.remaining > EPSILON and (not s.perishable or s.shelf_life >= days)],
        "expired_unused": [remaining(s) for s in stock if s.remaining > EPSILON and s.perishable and s.shelf_life < days],
        "perishable_first": [s.name for s in sorted(stock, key=lambda s: s.shelf_life)
                             if s.perishable and s.item_id in used_in][:3],
        "assumed_at_home": ["salt", "pepper", "cooking oil"],
    }


def _allocate(needs: list[list[str]], stock: list[Stock], servings: float,
              save: frozenset[str] = frozenset()) -> list[Allocation] | None:
    """Small fractional max-flow: share packs across slots without spending stock twice.

    Reverse edges let a flexible slot give back stock needed by a specific slot.
    No stock is mutated until the chosen recipe is committed by `consume`.
    """
    if not needs:
        return []
    ordered = sorted(stock, key=lambda s: (bool(s.tags & save), not s.opened, s.shelf_life, -s.remaining))
    count = len(needs) + len(ordered) + 2
    sink = count - 1
    capacity = [[0.0] * count for _ in range(count)]
    adjacency = [[] for _ in range(count)]

    def edge(a: int, b: int, amount: float) -> None:
        capacity[a][b] = amount
        adjacency[a].append(b)
        adjacency[b].append(a)

    for i, tags in enumerate(needs, start=1):
        edge(0, i, servings)
        for j, item in enumerate(ordered, start=1 + len(needs)):
            if item.tags & set(tags) and item.remaining > EPSILON:
                edge(i, j, servings)
    for j, item in enumerate(ordered, start=1 + len(needs)):
        edge(j, sink, max(0, item.remaining))
    while True:
        parents = [-1] * count
        parents[0] = 0
        queue = deque([0])
        while queue and parents[sink] < 0:
            node = queue.popleft()
            for nxt in adjacency[node]:
                if parents[nxt] < 0 and capacity[node][nxt] > EPSILON:
                    parents[nxt] = node
                    queue.append(nxt)
        if parents[sink] < 0:
            break
        amount, node = math.inf, sink
        while node != 0:
            prev = parents[node]
            amount = min(amount, capacity[prev][node])
            node = prev
        node = sink
        while node != 0:
            prev = parents[node]
            capacity[prev][node] -= amount
            capacity[node][prev] += amount
            node = prev
    if any(capacity[0][i] > EPSILON for i in range(1, len(needs) + 1)):
        return None
    return [Allocation(item, capacity[sink][j]) for j, item in enumerate(ordered, start=1 + len(needs))
            if capacity[sink][j] > EPSILON]


def _closest_missing(options: list[dict], stock: list[Stock], servings: float) -> dict:
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
