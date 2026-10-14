"""UC-08 — Meal-plan generation from the basket. Owner: Intake & Optimisation."""

from __future__ import annotations

from app.domain import Basket, MealPlan
from app.services import meal_planner
from app.services.catalogue import find_products


def generate(agent, basket: Basket) -> MealPlan:
    req = (basket.notes or {}).get("requirements", {})
    result = meal_planner.plan(
        basket,
        household_size=int(req.get("household_size", 1)),
        days=int(req.get("days", 7)),
        meals_per_day=float(req.get("meals_per_day", 2)),
    )
    # Recommended additional items for the meals that couldn't be planned (never auto-added).
    suggestions: dict[str, str] = {}
    for gap in result["missing"]:
        for tag in gap["missing_tags"]:
            if tag not in suggestions:
                found = find_products(agent.db, tag, limit=1)
                if found:
                    suggestions[tag] = found[0].name
    result["suggested_additions"] = [{"for": tag, "product": name} for tag, name in suggestions.items()]

    note = agent.think("meal_plan_notes", {
        "planned": result["planned"], "requested": result["requested"], "reused": result["reused"],
        "perishable_first": result["perishable_first"], "missing": len(result["missing"]),
    })
    plan = MealPlan(basket_id=basket.id, payload=result, summary=note.data)
    agent.db.add(plan)
    agent.db.flush()
    agent.log("generate_meal_plan", f"Planned {result['planned']} of {result['requested']} meals",
              rationale=note.data, basket_id=basket.id, session_id=basket.session_id, llm=note)
    return plan
