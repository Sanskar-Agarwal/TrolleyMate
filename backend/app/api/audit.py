"""UC-07 — agent audit log (founder sees raw prompts/responses). Owner: Platform & Governance.

The log is written only by the AI Technical Manager and has no write endpoints, so no
agent or shopper action can edit or remove a recorded decision.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.agents.context import AgentContext
from app.api.common import audit_out
from app.core.deps import agent_context
from app.domain import AuditRecord, EscalationCase, ShoppingSession
from app.domain.enums import CaseStatus, UserRole

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def audit_log(
    agent: str | None = None,
    session_id: int | None = None,
    basket_id: int | None = None,
    limit: int = Query(default=100, le=500),
    ctx: AgentContext = Depends(agent_context),
) -> list[dict]:
    founder = ctx.user.role == UserRole.founder
    stmt = select(AuditRecord).order_by(AuditRecord.id.desc()).limit(limit)
    if agent:
        stmt = stmt.where(AuditRecord.agent == agent)
    if session_id:
        stmt = stmt.where(AuditRecord.session_id == session_id)
    if basket_id:
        stmt = stmt.where(AuditRecord.basket_id == basket_id)
    if not founder:
        mine = select(ShoppingSession.id).where(ShoppingSession.shopper_id == ctx.user.id)
        stmt = stmt.where(AuditRecord.session_id.in_(mine))
    return [audit_out(r, full=founder) for r in ctx.db.scalars(stmt)]


@router.get("/stats")
def stats(ctx: AgentContext = Depends(agent_context)) -> dict:
    if ctx.user.role != UserRole.founder:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the founder can view system-wide audit statistics.")
    per_agent = ctx.db.execute(select(AuditRecord.agent, func.count()).group_by(AuditRecord.agent)).all()
    per_provider = ctx.db.execute(select(AuditRecord.provider, func.count()).group_by(AuditRecord.provider)).all()
    open_cases = ctx.db.scalar(select(func.count()).select_from(EscalationCase).where(EscalationCase.status != CaseStatus.resolved))
    return {
        "per_agent": {a: n for a, n in per_agent},
        "per_provider": {p: n for p, n in per_provider},
        "open_cases": open_cases,
        "llm": ctx.llm.status(),
        "policy": ctx.manager.policy(),
    }
