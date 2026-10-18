"""UC-08 — Meal-plan generation from the basket. Owner: Intake & Optimisation."""

from __future__ import annotations

from app.domain import Basket, MealPlan, ShoppingSession
from app.domain.enums import BasketStatus, ItemCompliance
from app.services import meal_planner
from app.services.catalogue import find_products
from app.services.session_state import active_constraints, household_of


def basket_snapshot(basket: Basket) -> list:
    return [[i.id, i.product_id, i.quantity, i.withheld, i.compliance] for i in sorted(basket.items, key=lambda i: i.id)]


def is_current(plan: MealPlan, basket: Basket) -> bool:
    return basket.status == BasketStatus.accepted and plan.payload.get("basket_snapshot") == basket_snapshot(basket)


def generate(agent, basket: Basket) -> MealPlan:
    if basket.status != BasketStatus.accepted:
        raise ValueError("Accept your basket before generating a meal plan.")
    session = agent.db.get(ShoppingSession, basket.session_id)
    record = active_constraints(agent.db, session)
    if record is None or record.id != basket.constraint_set_id:
        raise ValueError("Your constraints changed. Rebuild and accept your basket before planning meals.")
    if any(i.withheld or i.compliance != ItemCompliance.compliant for i in basket.items):
        raise ValueError("Resolve all dietary reviews before planning meals.")
    household = household_of(agent.db, session)
    restrictions = agent.ctx.compliance.restrictions_for(household, record.payload)
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
                for product in find_products(agent.db, tag, limit=10):
                    verdict = agent.ctx.compliance.screen_product(product, restrictions, household.id)
                    if verdict.status == ItemCompliance.compliant:
                        suggestions[tag] = product.name
                        break
    result["suggested_additions"] = [{"for": tag, "product": name} for tag, name in suggestions.items()]

    note = agent.think("meal_plan_notes", {
        "planned": result["planned"], "requested": result["requested"], "reused": result["reused"],
        "perishable_first": result["perishable_first"], "missing": len(result["missing"]),
    })
    result["basket_snapshot"] = basket_snapshot(basket)
    plan = MealPlan(basket_id=basket.id, payload=result, summary=note.data)
    agent.db.add(plan)
    agent.db.flush()
    agent.log("generate_meal_plan", f"Planned {result['planned']} of {result['requested']} meals",
              rationale=note.data, basket_id=basket.id, session_id=basket.session_id, llm=note)
    return plan
