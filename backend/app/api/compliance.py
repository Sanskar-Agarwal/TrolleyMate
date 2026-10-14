"""UC-06 / 1.2.11 endpoints — verify a basket, check a product, read verdicts. Owner: Compliance & Preferences."""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.agents.context import AgentContext
from app.api.common import basket_out, done, not_found, own_basket, own_household, own_session
from app.core.deps import agent_context
from app.domain import ComplianceVerdict, Product
from app.domain.enums import BasketStatus, VerdictStatus
from app.optimisation.types import Requirements
from app.services.session_state import active_constraints, household_of

router = APIRouter(tags=["compliance"])


@router.post("/baskets/{basket_id}/verify")
def verify(basket_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    b = own_basket(ctx, basket_id)
    s = own_session(ctx, b.session_id)
    cs = active_constraints(ctx.db, s)
    fields = Requirements.__dataclass_fields__
    saved = (b.notes or {}).get("requirements")
    req = Requirements(**{k: v for k, v in saved.items() if k in fields}) if saved else None
    verdict = ctx.compliance.verify(b, household_of(ctx.db, s), cs.payload if cs else {}, req)
    b.status = BasketStatus.pending_review if verdict.status == VerdictStatus.escalated else BasketStatus.verified
    b.recalc_total()
    return done(ctx, {"verdict": _verdict_out(verdict), "basket": basket_out(ctx, b)})


@router.get("/baskets/{basket_id}/verdicts")
def verdicts(basket_id: int, ctx: AgentContext = Depends(agent_context)) -> list[dict]:
    own_basket(ctx, basket_id)
    rows = ctx.db.scalars(select(ComplianceVerdict).where(ComplianceVerdict.basket_id == basket_id).order_by(ComplianceVerdict.id))
    return [_verdict_out(v) for v in rows]


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
