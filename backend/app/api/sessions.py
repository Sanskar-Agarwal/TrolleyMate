"""Shopping sessions and the chat entry point (supervisor routing). Owner: Platform / Intake."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.context import AgentContext
from app.api.common import basket_out, done, meal_plan_out, own_household, own_session
from app.core.deps import agent_context
from app.domain import MealPlan, ShoppingRequest, ShoppingSession
from app.domain.enums import SessionStatus
from app.services.session_state import active_constraints, latest_basket
from app.workflows import intake

router = APIRouter(prefix="/sessions", tags=["sessions"])


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def session_state(ctx: AgentContext, s: ShoppingSession) -> dict:
    basket = latest_basket(ctx.db, s.id)
    cs = active_constraints(ctx.db, s)
    req = ctx.db.scalar(
        select(ShoppingRequest).where(ShoppingRequest.session_id == s.id).order_by(ShoppingRequest.id.desc()).limit(1)
    )
    plan = (
        ctx.db.scalar(select(MealPlan).where(MealPlan.basket_id == basket.id).order_by(MealPlan.id.desc()).limit(1))
        if basket else None
    )
    return {
        "session": {"id": s.id, "goal": s.goal, "status": s.status, "created_at": s.created_at.isoformat() if s.created_at else None},
        "intake": intake.state(req) if req else None,
        "constraints": {"version": cs.version, "payload": cs.payload, "origin": cs.origin} if cs else None,
        "basket": basket_out(ctx, basket) if basket else None,
        "meal_plan": meal_plan_out(plan) if plan else None,
        "chat": s.chat_history or [],
    }


@router.post("")
def new_session(ctx: AgentContext = Depends(agent_context)) -> dict:
    h = own_household(ctx)
    s = ShoppingSession(shopper_id=ctx.user.id, household_id=h.id)
    ctx.db.add(s)
    ctx.db.flush()
    return done(ctx, session_state(ctx, s))


@router.get("/current")
def current_session(ctx: AgentContext = Depends(agent_context)) -> dict:
    s = ctx.db.scalar(
        select(ShoppingSession)
        .where(ShoppingSession.shopper_id == ctx.user.id, ShoppingSession.status != SessionStatus.closed)
        .order_by(ShoppingSession.id.desc())
        .limit(1)
    )
    if s is None:
        return new_session(ctx)
    return done(ctx, session_state(ctx, s))


@router.get("/{session_id}")
def get_session(session_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    return session_state(ctx, own_session(ctx, session_id))


@router.post("/{session_id}/chat")
def chat(session_id: int, body: ChatIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    s = own_session(ctx, session_id)
    response = ctx.shopper.handle_message(s, body.text)
    ctx.db.flush()
    return done(ctx, {"response": response, "state": session_state(ctx, s)})
