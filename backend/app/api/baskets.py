"""UC-02 / UC-03 / UC-07 basket endpoints — build, negotiate, accept, explain. Owner: Intake & Optimisation
(negotiation: Negotiation & Substitution; explain: Platform & Governance)."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.context import AgentContext
from app.api.common import basket_out, done, own_basket, own_item, own_session
from app.core.deps import agent_context
from app.domain import Basket
from app.domain.enums import BasketStatus, ItemCompliance, OptimisationGoal
from app.optimisation import STRATEGIES
from app.services.build_control import BuildCancelled, BuildConflict, builds, checkpoint

router = APIRouter(tags=["baskets"])


class BuildIn(BaseModel):
    goal: OptimisationGoal | None = None
    operation_id: UUID | None = None


class NegotiateIn(BaseModel):
    option_id: str | None = None
    budget: float | None = Field(default=None, gt=0)
    days: int | None = Field(default=None, ge=1, le=31)
    goal: OptimisationGoal | None = None
    operation_id: UUID | None = None


@router.get("/goals")
def goals() -> list[dict]:
    return [{"id": g, "label": s.label} for g, s in STRATEGIES.items()]


def _outcome(ctx: AgentContext, outcome) -> dict:
    if outcome.status == "ok":
        return {"status": "ok", "basket": basket_out(ctx, outcome.basket)}
    if outcome.status == "retryable":
        return {"status": "retryable", "reason": outcome.reason, "message": outcome.message}
    return {"status": "infeasible", "negotiation": outcome.negotiation}


def _controlled_build(ctx: AgentContext, session_id: int, operation_id: UUID | None, action) -> dict:
    try:
        with builds.track(session_id, str(operation_id or uuid4())) as operation:
            # Ownership was checked before taking the operation gate. If an
            # earlier build committed during that check, reload its active
            # constraints instead of using the identity map's older snapshot.
            ctx.db.expire_all()
            result = _outcome(ctx, action())
            checkpoint()
            builds.commit(operation, ctx.db.commit)
            return {**result, "trace": ctx.trace}
    except BuildCancelled:
        ctx.db.rollback()
        return {"status": "cancelled", "message": "Basket build cancelled. Your previous basket and constraints are unchanged.", "trace": []}
    except BuildConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        ctx.db.rollback()
        raise


@router.post("/sessions/{session_id}/basket")
def build_basket(session_id: int, body: BuildIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    session = own_session(ctx, session_id)
    return _controlled_build(ctx, session_id, body.operation_id, lambda: ctx.shopper.orchestrate(session, body.goal))


@router.post("/sessions/{session_id}/negotiate")
def negotiate(session_id: int, body: NegotiateIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    s = own_session(ctx, session_id)
    return _controlled_build(ctx, session_id, body.operation_id,
                             lambda: ctx.shopper.negotiate(s, option_id=body.option_id, budget=body.budget, days=body.days, goal=body.goal))


@router.post("/sessions/{session_id}/basket-builds/{operation_id}/cancel")
def cancel_build(session_id: int, operation_id: UUID, ctx: AgentContext = Depends(agent_context)) -> dict:
    own_session(ctx, session_id)
    try:
        return {**builds.cancel(session_id, str(operation_id)), "trace": []}
    except BuildConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/baskets/{basket_id}")
def get_basket(basket_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    return basket_out(ctx, own_basket(ctx, basket_id))


@router.post("/baskets/{basket_id}/accept")
def accept_basket(basket_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    b = own_basket(ctx, basket_id)
    session = own_session(ctx, b.session_id)
    if b.status not in (BasketStatus.verified, BasketStatus.accepted):
        raise ValueError("Only a verified, current basket can be accepted. Resolve any pending review first.")
    if b.constraint_set_id != session.active_constraint_set_id:
        raise ValueError("Your constraints changed. Rebuild the basket before accepting it.")
    if not b.items or any(i.withheld or i.compliance != ItemCompliance.compliant for i in b.items):
        raise ValueError("Every item must pass compliance before you accept the basket.")
    b.recalc_total()
    if b.budget is not None and b.total > b.budget + 0.001:
        raise ValueError("This basket exceeds your budget. Adjust it before accepting.")
    ctx.compliance.require_nutrition_adequate(b)  # 1.2.11: every gap met or explicitly accepted
    for old in ctx.db.scalars(select(Basket).where(Basket.session_id == b.session_id, Basket.id < b.id,
                                                  Basket.status != BasketStatus.superseded)):
        old.status = BasketStatus.superseded
    b.status = BasketStatus.accepted
    ctx.shopper.log("accept_basket", f"Shopper accepted basket #{b.id} (${b.total:.2f})", basket_id=b.id, session_id=b.session_id)
    return done(ctx, {"basket": basket_out(ctx, b)})


@router.get("/baskets/{basket_id}/explain")
def explain_basket(basket_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    return done(ctx, ctx.manager.explain_for(own_basket(ctx, basket_id)))


@router.get("/baskets/{basket_id}/items/{item_id}/explain")
def explain_item(basket_id: int, item_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    return done(ctx, ctx.manager.explain_item(own_item(ctx, basket_id, item_id)))
