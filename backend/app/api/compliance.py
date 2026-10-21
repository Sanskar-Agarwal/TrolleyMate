"""UC-06 / 1.2.11 endpoints — verify a basket, check a product, read verdicts, nutrition coverage,
repairs and accepted exceptions. Owner: Compliance & Preferences."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.agents.context import AgentContext
from app.agents.nutrition_compliance import saved_requirements
from app.api.common import basket_out, done, not_found, own_basket, own_household, own_session
from app.core.deps import agent_context
from app.domain import ComplianceVerdict, Product
from app.domain.enums import BasketStatus, VerdictStatus
from app.services.session_state import active_constraints, household_of

router = APIRouter(tags=["compliance"])
_NO_REQUIREMENTS = "This basket has no meal requirements to check nutrition against."


class ExceptionIn(BaseModel):
    nutrients: list[str]
    note: str = ""


@router.post("/baskets/{basket_id}/verify")
def verify(basket_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    b = own_basket(ctx, basket_id)
    s = own_session(ctx, b.session_id)
    cs = active_constraints(ctx.db, s)
    verdict = ctx.compliance.verify(b, household_of(ctx.db, s), cs.payload if cs else {}, saved_requirements(b))
    b.status = BasketStatus.pending_review if verdict.status == VerdictStatus.escalated else BasketStatus.verified
    b.recalc_total()
    return done(ctx, {"verdict": _verdict_out(verdict), "basket": basket_out(ctx, b)})


@router.get("/baskets/{basket_id}/verdicts")
def verdicts(basket_id: int, ctx: AgentContext = Depends(agent_context)) -> list[dict]:
    own_basket(ctx, basket_id)
    rows = ctx.db.scalars(select(ComplianceVerdict).where(ComplianceVerdict.basket_id == basket_id).order_by(ComplianceVerdict.id))
    return [_verdict_out(v) for v in rows]


@router.get("/baskets/{basket_id}/nutrition")
def nutrition(basket_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    """1.2.11 — current coverage, and candidate repairs for the gaps the shopper hasn't accepted."""
    b = own_basket(ctx, basket_id)
    s = own_session(ctx, b.session_id)
    current = ctx.compliance.current_nutrition(b)
    if current is None:
        raise ValueError(_NO_REQUIREMENTS)
    cs = active_constraints(ctx.db, s)
    repairs = ctx.compliance.nutrition_repairs(b, current, household_of(ctx.db, s), cs.payload if cs else {})
    return done(ctx, {"nutrition": current, "repairs": repairs})


@router.post("/baskets/{basket_id}/nutrition/exceptions")
def accept_exception(basket_id: int, body: ExceptionIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    """UC-02 ext 4b — the shopper explicitly accepts identified nutrition gaps; it is recorded and audited."""
    b = own_basket(ctx, basket_id)
    if own_session(ctx, b.session_id).shopper_id != ctx.user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the shopper can accept a nutrition gap for their basket.")
    if b.status == BasketStatus.superseded:
        raise ValueError("This basket has been replaced. Review the current basket instead.")
    req = saved_requirements(b)
    if req is None:
        raise ValueError(_NO_REQUIREMENTS)
    ctx.compliance.accept_nutrition_exception(b, req, body.nutrients, body.note)
    return done(ctx, {"basket": basket_out(ctx, b)})


@router.get("/products/{product_id}/compliance")
def check_product(product_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    """Check one product against the signed-in shopper's household."""
    p = ctx.db.get(Product, product_id)
    if p is None:
        raise not_found("Product")
    h = own_household(ctx)
    finding = ctx.compliance.screen_product(p, ctx.compliance.restrictions_for(h, None), h.id)
    return done(ctx, finding.as_dict())


def _verdict_out(v: ComplianceVerdict) -> dict:
    return {
        "id": v.id, "status": v.status, "confidence": v.confidence, "source": v.source, "evidence": v.evidence,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }
