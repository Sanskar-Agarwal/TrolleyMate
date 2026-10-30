"""UC-01 endpoints — submit, clarify, correct, form, confirm, cancel. Owner: Intake & Optimisation."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from app.agents.context import AgentContext
from app.api.common import done, not_found, own_session
from app.core.deps import agent_context
from app.domain import ShoppingRequest
from app.workflows import intake

router = APIRouter(tags=["intake"])


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class CorrectionIn(BaseModel):
    text: str | None = Field(default=None, max_length=2000)
    patch: dict | None = None


class FormIn(BaseModel):
    budget: float | None = Field(default=None, gt=0, strict=True, allow_inf_nan=False)
    household_size: int | None = Field(default=None, ge=1, le=20, strict=True)
    meals_per_day: float | None = Field(default=None, gt=0, le=5, strict=True, allow_inf_nan=False)
    days: int | None = Field(default=None, ge=1, le=31, strict=True)
    restrictions: list[dict] | None = None
    nutritional_targets: list[dict] | None = None
    preferences: list[str] | None = None
    goal_hint: str | None = None


def _request(ctx: AgentContext, request_id: int) -> ShoppingRequest:
    req = ctx.db.get(ShoppingRequest, request_id)
    if req is None:
        raise not_found("Request")
    own_session(ctx, req.session_id)
    return req


@router.post("/sessions/{session_id}/requests")
def submit_request(session_id: int, body: TextIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    req = ctx.shopper.extract_constraints(own_session(ctx, session_id), body.text)
    return done(ctx, {"intake": intake.state(req)})


@router.post("/requests/{request_id}/clarify")
def clarify(request_id: int, body: TextIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    req = ctx.shopper.clarify(_request(ctx, request_id), body.text)
    return done(ctx, {"intake": intake.state(req)})


@router.post("/requests/{request_id}/correct")
def correct(request_id: int, body: CorrectionIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    req = ctx.shopper.correct(_request(ctx, request_id), text=body.text, patch=body.patch)
    return done(ctx, {"intake": intake.state(req)})


@router.post("/requests/{request_id}/form")
def submit_form(request_id: int, body: FormIn, ctx: AgentContext = Depends(agent_context)) -> dict:
    req = ctx.shopper.submit_form(_request(ctx, request_id), body.model_dump(exclude_unset=True))
    return done(ctx, {"intake": intake.state(req)})


@router.post("/requests/{request_id}/confirm")
def confirm(request_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    req = _request(ctx, request_id)
    try:
        cs = ctx.shopper.confirm(req)
        return done(ctx, {"intake": intake.state(req), "constraints": {"version": cs.version, "payload": cs.payload, "origin": cs.origin}})
    except SQLAlchemyError as exc:
        ctx.db.rollback()
        raise intake.IntakeError("Saving failed. Your previous constraints are unchanged. Try again.") from exc


@router.post("/requests/{request_id}/cancel")
def cancel(request_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    req = ctx.shopper.cancel(_request(ctx, request_id))
    return done(ctx, {"intake": intake.state(req)})
