"""1.2.12 — Taste & preference memory. Owner: Compliance & Preferences.

Only the signed-in shopper's own household is reachable: every route goes through
`/households/me`, so another account's preference is simply not found (404), staff included.
Audit records name the kind and id of a change but never its value, so a forgotten preference
leaves no copy behind in the log (Taste & Preference Memory implies Enhanced Data Protection).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.agents.context import AgentContext
from app.api.common import done, household_out, not_found, own_household
from app.core.deps import agent_context
from app.domain import AuditRecord, Household, Preference
from app.services.audit_privacy import audit_payload
from app.services.preference_memory import PreferenceConflict, find_conflict, kind_label, normalise_value

router = APIRouter(prefix="/households/me/preferences", tags=["preferences"])


class PreferenceIn(BaseModel):
    kind: str = Field(pattern="^(dislike|like|brand|avoid_brand)$")
    value: str = Field(min_length=1, max_length=120)

    @field_validator("value")
    @classmethod
    def _normalised(cls, value: str) -> str:
        value = normalise_value(value)
        if not value:
            raise ValueError("Say what the preference is about.")
        return value


def _own_preference(h: Household, preference_id: int) -> Preference:
    pref = next((p for p in h.preferences if p.id == preference_id), None)
    if pref is None:
        raise not_found("Preference")
    return pref


def _conflict(h: Household, body: PreferenceIn, ignore: int | None = None) -> Preference | None:
    try:
        return find_conflict(h.preferences, body.kind, body.value, ignore=ignore)
    except PreferenceConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


def _reply(ctx: AgentContext, h: Household) -> dict:
    return done(ctx, {"household": household_out(h), "preferences": ctx.compliance.describe_preferences(h)})


@router.get("")
def list_preferences(ctx: AgentContext = Depends(agent_context)) -> list[dict]:
    return ctx.compliance.describe_preferences(own_household(ctx))


@router.post("")
def add_preference(body: PreferenceIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    h = own_household(ctx)
    if _conflict(h, body) is None:
        pref = Preference(kind=body.kind, value=body.value)
        h.preferences.append(pref)
        ctx.db.flush()
        ctx.manager.log("update_preferences", f"Remembered a {kind_label(pref.kind)} preference (#{pref.id})")
    return _reply(ctx, h)


@router.put("/{preference_id}")
def change_preference(preference_id: int, body: PreferenceIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    h = own_household(ctx)
    pref = _own_preference(h, preference_id)
    if (pref.kind, pref.value) != (body.kind, body.value):
        if _conflict(h, body, ignore=pref.id) is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"You've already saved \"{kind_label(body.kind)}: {body.value}\".")
        pref.kind, pref.value, pref.source = body.kind, body.value, "user"  # the shopper has now stated it
        pref.meta = {**(pref.meta or {}), "updated_at": datetime.now().isoformat(timespec="seconds")}
        ctx.manager.log("update_preferences", f"Changed preference #{pref.id} (now a {kind_label(pref.kind)})")
    return _reply(ctx, h)


@router.delete("/{preference_id}")
def remove_preference(preference_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    h = own_household(ctx)
    pref = _own_preference(h, preference_id)
    h.preferences.remove(pref)  # delete-orphan: the row itself is deleted, not just unlinked
    # Remove private preference copies from this owner's legacy oversight payloads too.
    # Confirmed shopping instructions remain a separate, historical agreement.
    for record in ctx.db.scalars(select(AuditRecord).where(AuditRecord.actor_user_id == ctx.user.id)):
        record.payload = audit_payload(record.payload, record.action)
    ctx.db.flush()
    ctx.manager.log("update_preferences", f"Forgot a {kind_label(pref.kind)} preference (#{preference_id})")
    return _reply(ctx, h)
