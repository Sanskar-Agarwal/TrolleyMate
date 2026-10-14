"""UC-02 / UC-03 / UC-07 basket endpoints — build, negotiate, accept, explain. Owner: Intake & Optimisation
(negotiation: Negotiation & Substitution; explain: Platform & Governance)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.agents.context import AgentContext
from app.api.common import basket_out, done, own_basket, own_item, own_session
from app.core.deps import agent_context
from app.domain.enums import BasketStatus, OptimisationGoal
from app.optimisation import STRATEGIES

router = APIRouter(tags=["baskets"])


class BuildIn(BaseModel):
    goal: OptimisationGoal | None = None


class NegotiateIn(BaseModel):
    option_id: str | None = None
    budget: float | None = Field(default=None, gt=0)
    days: int | None = Field(default=None, ge=1, le=31)
    goal: OptimisationGoal | None = None


@router.get("/goals")
def goals() -> list[dict]:
    return [{"id": g, "label": s.label} for g, s in STRATEGIES.items()]


def _outcome(ctx: AgentContext, outcome) -> dict:
    if outcome.status == "ok":
        return done(ctx, {"status": "ok", "basket": basket_out(ctx, outcome.basket)})
    return done(ctx, {"status": "infeasible", "negotiation": outcome.negotiation})


@router.post("/sessions/{session_id}/basket")
def build_basket(session_id: int, body: BuildIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    return _outcome(ctx, ctx.shopper.orchestrate(own_session(ctx, session_id), body.goal))


@router.post("/sessions/{session_id}/negotiate")
def negotiate(session_id: int, body: NegotiateIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    s = own_session(ctx, session_id)
    return _outcome(ctx, ctx.shopper.negotiate(s, option_id=body.option_id, budget=body.budget, days=body.days, goal=body.goal))


@router.get("/baskets/{basket_id}")
def get_basket(basket_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    return basket_out(ctx, own_basket(ctx, basket_id))


@router.post("/baskets/{basket_id}/accept")
def accept_basket(basket_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    b = own_basket(ctx, basket_id)
    if b.status == BasketStatus.pending_review:
        raise ValueError("Some items are still waiting for dietitian review.")
    b.status = BasketStatus.accepted
    ctx.shopper.log("accept_basket", f"Shopper accepted basket #{b.id} (${b.total:.2f})", basket_id=b.id, session_id=b.session_id)
    return done(ctx, {"basket": basket_out(ctx, b)})


@router.get("/baskets/{basket_id}/explain")
def explain_basket(basket_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    return done(ctx, ctx.manager.explain_for(own_basket(ctx, basket_id)))


@router.get("/baskets/{basket_id}/items/{item_id}/explain")
def explain_item(basket_id: int, item_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    return done(ctx, ctx.manager.explain_item(own_item(ctx, basket_id, item_id)))
