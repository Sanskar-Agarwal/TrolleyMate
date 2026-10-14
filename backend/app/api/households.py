"""UC-10 — Account, household & dietary profile management. Owner: Platform & Governance."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.agents.context import AgentContext
from app.api.common import done, household_out, not_found, own_household
from app.core.deps import agent_context
from app.domain import DietaryProfile, HouseholdMember
from app.domain.enums import RestrictionKind, Severity
from app.services.dietary_rules import RESTRICTION_RULES, normalise_restriction

router = APIRouter(tags=["households"])


class RestrictionIn(BaseModel):
    restriction: str
    kind: RestrictionKind | None = None
    severity: Severity = Severity.severe


class MemberIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    age_group: str = "adult"
    restrictions: list[RestrictionIn] = []


class HouseholdIn(BaseModel):
    name: str | None = None
    region: str | None = None


@router.get("/dietary/restrictions")
def vocabulary() -> list[dict]:
    return [{"id": k, "label": v["label"], "kind": v["kind"]} for k, v in RESTRICTION_RULES.items()]


@router.get("/households/me")
def get_household(ctx: AgentContext = Depends(agent_context)) -> dict:
    return household_out(own_household(ctx))


@router.put("/households/me")
def update_household(body: HouseholdIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    h = own_household(ctx)
    if body.name:
        h.name = body.name
    if body.region:
        h.region = body.region
    return done(ctx, {"household": household_out(h)})


def _set_restrictions(member: HouseholdMember, items: list[RestrictionIn]) -> None:
    member.dietary_profiles.clear()
    for r in items:
        rid = normalise_restriction(r.restriction)
        if rid not in RESTRICTION_RULES:
            raise HTTPException(400, f"Unknown restriction '{r.restriction}'.")
        member.dietary_profiles.append(
            DietaryProfile(restriction=rid, kind=r.kind or RESTRICTION_RULES[rid]["kind"], severity=r.severity)
        )


@router.post("/households/me/members")
def add_member(body: MemberIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    h = own_household(ctx)
    member = HouseholdMember(name=body.name, age_group=body.age_group)
    _set_restrictions(member, body.restrictions)
    h.add_member(member)
    ctx.db.flush()
    ctx.manager.log("update_profile", f"Added household member {member.name}")
    return done(ctx, {"household": household_out(h)})


@router.put("/households/me/members/{member_id}")
def update_member(member_id: int, body: MemberIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    h = own_household(ctx)
    member = next((m for m in h.members if m.id == member_id), None)
    if member is None:
        raise not_found("Member")
    member.name, member.age_group = body.name, body.age_group
    _set_restrictions(member, body.restrictions)
    ctx.manager.log("update_profile", f"Updated {member.name}: {', '.join(r.restriction for r in body.restrictions) or 'no restrictions'}")
    return done(ctx, {"household": household_out(h)})


@router.delete("/households/me/members/{member_id}")
def delete_member(member_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    h = own_household(ctx)
    member = next((m for m in h.members if m.id == member_id), None)
    if member is None:
        raise not_found("Member")
    h.members.remove(member)
    ctx.manager.log("update_profile", f"Removed household member {member.name}")
    return done(ctx, {"household": household_out(h)})
