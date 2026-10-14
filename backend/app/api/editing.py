"""UC-09 endpoint. Owner: Pricing & Editing."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.agents.context import AgentContext
from app.api.common import basket_out, done, own_basket
from app.core.deps import agent_context

router = APIRouter(tags=["editing"])


class EditIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@router.post("/baskets/{basket_id}/edit")
def edit(basket_id: int, body: EditIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    result = ctx.shopper.edit_basket(own_basket(ctx, basket_id), body.text)
    out = {k: v for k, v in result.items() if k != "basket"}
    if result.get("basket") is not None:
        out["basket"] = basket_out(ctx, result["basket"])
    return done(ctx, out)
