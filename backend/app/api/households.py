"""UC-10 — Account, household & dietary profile management. Owner: Platform & Governance."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

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
    age_group: Literal["adult", "teen", "child", "senior"] = "adult"
    restrictions: list[RestrictionIn] = []

    @field_validator("name")
    @classmethod
    def _named(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Give the member a name.")
        return value


class HouseholdIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=80)


@router.get("/dietary/restrictions")
def vocabulary() -> list[dict]:
    return [{"id": k, "label": v["label"], "kind": v["kind"]} for k, v in RESTRICTION_RULES.items()]


@router.get("/households/me")
def get_household(ctx: AgentContext = Depends(agent_context)) -> dict:
    return household_out(own_household(ctx))


@router.put("/households/me")
def update_household(body: HouseholdIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    h = own_household(ctx)
    if body.name and body.name.strip():
        h.name = body.name.strip()
    if body.region and body.region.strip():
        h.region = body.region.strip()
    return done(ctx, {"household": household_out(h)})


def _validated(items: list[RestrictionIn]) -> list[DietaryProfile]:
    """Check every restriction before anything is changed, so a rejected save leaves the
    last valid profile exactly as it was (UC-10 failure scenario)."""
    profiles: dict[str, DietaryProfile] = {}
    for r in items:
        rid = normalise_restriction(r.restriction)
        if rid not in RESTRICTION_RULES:
            raise HTTPException(400, f"Unknown restriction '{r.restriction}'. Your saved profile hasn't changed.")
        if rid in profiles:
            raise HTTPException(400, f"{RESTRICTION_RULES[rid]['label']} is listed twice. Your saved profile hasn't changed.")
        profiles[rid] = DietaryProfile(restriction=rid, kind=r.kind or RESTRICTION_RULES[rid]["kind"], severity=r.severity)
    return list(profiles.values())


def _replace_restrictions(member: HouseholdMember, profiles: list[DietaryProfile]) -> None:
    member.dietary_profiles.clear()
    member.dietary_profiles.extend(profiles)


def _summary(member: HouseholdMember) -> str:
    return f"{len(member.dietary_profiles)} restriction(s)"


@router.post("/households/me/members")
def add_member(body: MemberIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    h = own_household(ctx)
    profiles = _validated(body.restrictions)
    member = HouseholdMember(name=body.name, age_group=body.age_group)
    _replace_restrictions(member, profiles)
    h.add_member(member)
    ctx.db.flush()
    ctx.manager.log("update_profile", f"Added household member #{member.id} with {_summary(member)}")
    return done(ctx, {"household": household_out(h)})


@router.put("/households/me/members/{member_id}")
def update_member(member_id: int, body: MemberIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    h = own_household(ctx)
    member = next((m for m in h.members if m.id == member_id), None)
    if member is None:
        raise not_found("Member")
    profiles = _validated(body.restrictions)
    member.name, member.age_group = body.name, body.age_group
    _replace_restrictions(member, profiles)
    ctx.manager.log("update_profile", f"Updated household member #{member.id}: now {_summary(member)}")
    return done(ctx, {"household": household_out(h)})


@router.delete("/households/me/members/{member_id}")
def delete_member(member_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    h = own_household(ctx)
    member = next((m for m in h.members if m.id == member_id), None)
    if member is None:
        raise not_found("Member")
    if len(h.members) <= 1:
        raise HTTPException(400, "A household needs at least one member.")
    h.members.remove(member)
    ctx.manager.log("update_profile", f"Removed household member #{member_id}")
    return done(ctx, {"household": household_out(h)})
