"""UC-04 endpoints. Owner: Negotiation & Substitution."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.agents.context import AgentContext
from app.api.common import basket_out, done, not_found, own_item, own_session, substitution_out
from app.core.deps import agent_context
from app.domain import Substitution
from app.domain.enums import SubReason

router = APIRouter(tags=["substitutions"])


class SubstituteIn(BaseModel):
    reason: SubReason = SubReason.user_requested


def _sub(ctx: AgentContext, sub_id: int) -> Substitution:
    sub = ctx.db.get(Substitution, sub_id)
    if sub is None:
        raise not_found("Substitution")
    own_session(ctx, sub.session_id)
    return sub


@router.post("/baskets/{basket_id}/items/{item_id}/substitute")
def propose(basket_id: int, item_id: int, body: SubstituteIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    item = own_item(ctx, basket_id, item_id)
    basket = item.basket
    sub = ctx.shopper.find_substitute(item, body.reason)
    return done(ctx, {"substitution": substitution_out(sub), "basket": basket_out(ctx, basket)})


@router.post("/substitutions/{sub_id}/accept")
def accept(sub_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    sub = _sub(ctx, sub_id)
    basket = ctx.shopper.accept_substitution(sub)
    return done(ctx, {"substitution": substitution_out(sub), "basket": basket_out(ctx, basket)})


@router.post("/substitutions/{sub_id}/reject")
def reject(sub_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    sub = _sub(ctx, sub_id)
    basket = ctx.shopper.reject_substitution(sub)
    return done(ctx, {"substitution": substitution_out(sub), "basket": basket_out(ctx, basket)})
