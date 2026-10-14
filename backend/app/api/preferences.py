"""1.2.12 — Taste & preference memory. Owner: Compliance & Preferences."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.agents.context import AgentContext
from app.api.common import done, household_out, not_found, own_household
from app.core.deps import agent_context
from app.domain import Preference

router = APIRouter(prefix="/households/me/preferences", tags=["preferences"])

KINDS = ("dislike", "like", "brand", "avoid_brand")


class PreferenceIn(BaseModel):
    kind: str = Field(pattern="^(dislike|like|brand|avoid_brand)$")
    value: str = Field(min_length=1, max_length=120)


@router.get("")
def list_preferences(ctx: AgentContext = Depends(agent_context)) -> list[dict]:
    return household_out(own_household(ctx))["preferences"]


@router.post("")
def add_preference(body: PreferenceIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    h = own_household(ctx)
    value = body.value.strip().lower()
    if not any(p.kind == body.kind and p.value == value for p in h.preferences):
        h.preferences.append(Preference(kind=body.kind, value=value))
    ctx.manager.log("update_preferences", f"Remembered {body.kind}: {value}")
    return done(ctx, {"household": household_out(h)})


@router.delete("/{preference_id}")
def remove_preference(preference_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    h = own_household(ctx)
    pref = next((p for p in h.preferences if p.id == preference_id), None)
    if pref is None:
        raise not_found("Preference")
    h.preferences.remove(pref)
    ctx.manager.log("update_preferences", f"Forgot {pref.kind}: {pref.value}")
    return done(ctx, {"household": household_out(h)})
