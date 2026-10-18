"""UC-08 endpoints. Owner: Intake & Optimisation."""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.agents.context import AgentContext
from app.api.common import done, meal_plan_out, not_found, own_basket
from app.core.deps import agent_context
from app.domain import MealPlan
from app.workflows.meal_planning import is_current

router = APIRouter(tags=["meal plans"])


@router.post("/baskets/{basket_id}/meal-plan")
def generate(basket_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    plan = ctx.shopper.plan_meals(own_basket(ctx, basket_id))
    return done(ctx, {"meal_plan": meal_plan_out(plan)})


@router.get("/baskets/{basket_id}/meal-plan")
def latest(basket_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    basket = own_basket(ctx, basket_id)
    plan = ctx.db.scalar(select(MealPlan).where(MealPlan.basket_id == basket_id).order_by(MealPlan.id.desc()).limit(1))
    if plan is None or not is_current(plan, basket):
        raise not_found("Meal plan")
    return meal_plan_out(plan)
