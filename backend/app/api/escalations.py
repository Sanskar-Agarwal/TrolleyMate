"""UC-06 ext — dietitian review queue & founder exception queue. Owner: Platform & Governance."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.context import AgentContext
from app.api.common import case_out, done, not_found
from app.core.db import get_db
from app.core.deps import require_role
from app.domain import EscalationCase, User
from app.domain.enums import CaseStatus, UserRole, VerdictStatus
from app.llm import get_llm
from app.workflows import escalation

router = APIRouter(prefix="/escalations", tags=["escalations"])

reviewer = require_role(UserRole.dietitian, UserRole.founder)


def reviewer_context(user: User = Depends(reviewer), db=Depends(get_db)) -> AgentContext:
    return AgentContext(db=db, llm=get_llm(), user=user)


class QuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class ResolveIn(BaseModel):
    decision: VerdictStatus
    note: str = Field(default="", max_length=2000)


class AssignIn(BaseModel):
    reviewer_id: int


def _case(ctx: AgentContext, case_id: int) -> EscalationCase:
    case = ctx.db.get(EscalationCase, case_id)
    if case is None:
        raise not_found("Case")
    return case


@router.get("")
def queue(status: str | None = None, mine: bool = False, ctx: AgentContext = Depends(reviewer_context)) -> dict:
    escalation.sweep_sla(ctx.compliance)
    stmt = select(EscalationCase).order_by(EscalationCase.status == CaseStatus.resolved, EscalationCase.id.desc())
    if status == "open":
        stmt = stmt.where(EscalationCase.status != CaseStatus.resolved)
    elif status:
        stmt = stmt.where(EscalationCase.status == status)
    if mine or ctx.user.role == UserRole.dietitian:
        stmt = stmt.where((EscalationCase.assigned_to_id == ctx.user.id) | (EscalationCase.status == CaseStatus.open))
    cases = [case_out(c) for c in ctx.db.scalars(stmt)]
    return done(ctx, {"cases": cases})


@router.get("/reviewers")
def reviewers(ctx: AgentContext = Depends(reviewer_context)) -> list[dict]:
    users = ctx.db.scalars(select(User).where(User.role.in_([UserRole.dietitian, UserRole.founder])))
    return [{"id": u.id, "display_name": u.display_name, "role": u.role} for u in users]


@router.get("/{case_id}")
def get_case(case_id: int, ctx: AgentContext = Depends(reviewer_context)) -> dict:
    return case_out(_case(ctx, case_id))


@router.post("/{case_id}/assign")
def assign(case_id: int, body: AssignIn, ctx: AgentContext = Depends(reviewer_context)) -> dict:
    target = ctx.db.get(User, body.reviewer_id)
    if target is None:
        raise not_found("Reviewer")
    # Dietitians can take a case themselves; only the founder hands cases to someone else.
    case = _case(ctx, case_id)
    if ctx.user.role != UserRole.founder:
        if target.id != ctx.user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the founder can assign a case to another reviewer.")
        if case.assigned_to_id not in (None, ctx.user.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This case is already assigned to another reviewer.")
    case = escalation.assign(ctx.compliance, case, target)
    return done(ctx, {"case": case_out(case)})


@router.post("/{case_id}/begin")
def begin(case_id: int, ctx: AgentContext = Depends(reviewer_context)) -> dict:
    case = escalation.begin_review(ctx.compliance, _case(ctx, case_id), ctx.user)
    return done(ctx, {"case": case_out(case)})


@router.post("/{case_id}/request-info")
def request_info(case_id: int, body: QuestionIn, ctx: AgentContext = Depends(reviewer_context)) -> dict:
    case = escalation.request_information(ctx.compliance, _case(ctx, case_id), ctx.user, body.question)
    return done(ctx, {"case": case_out(case)})


@router.post("/{case_id}/resolve")
def resolve(case_id: int, body: ResolveIn, ctx: AgentContext = Depends(reviewer_context)) -> dict:
    case = escalation.resolve(ctx.compliance, _case(ctx, case_id), ctx.user, body.decision, body.note)
    return done(ctx, {"case": case_out(case)})
