"""Domain::SafetyAudit — ComplianceVerdict, EscalationCase, AuditRecord."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.domain.enums import CaseStatus, VerdictStatus


class ComplianceVerdict(Base):
    __tablename__ = "compliance_verdicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    basket_id: Mapped[int | None] = mapped_column(ForeignKey("baskets.id"), default=None)
    status: Mapped[str] = mapped_column(String(20), default=VerdictStatus.pending)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # {"products": [{product_id, name, status, findings, confidence}], "nutrition": {...}}
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(20), default="agent")  # agent | human
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def requires_review(self, threshold: float) -> bool:
        return self.status == VerdictStatus.escalated or self.confidence < threshold


class EscalationCase(Base):
    __tablename__ = "escalation_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    verdict_id: Mapped[int] = mapped_column(ForeignKey("compliance_verdicts.id"))
    basket_id: Mapped[int] = mapped_column(ForeignKey("baskets.id"))
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id"), index=True)
    basket_item_id: Mapped[int | None] = mapped_column(ForeignKey("basket_items.id"), default=None)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default=CaseStatus.open)
    # The household requirements at the time of escalation (so the reviewer sees what the agent saw).
    requirements: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    # Info requests / supplied answers: [{"from": "dietitian"|"agent", "text": ..., "at": iso}]
    thread: Mapped[list] = mapped_column(JSON, default=list)
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    review_started_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    resolution: Mapped[str | None] = mapped_column(String(20), default=None)  # passed | failed
    resolution_note: Mapped[str | None] = mapped_column(Text, default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    product = relationship("Product")
    assignee = relationship("User", foreign_keys=[assigned_to_id])


class AuditRecord(Base):
    """One significant agent decision (1.2.14). Written only through TechnicalManagerAgent.record."""

    __tablename__ = "audit_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    agent: Mapped[str] = mapped_column(String(60), index=True)
    action: Mapped[str] = mapped_column(String(80))
    decision: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    model_version: Mapped[str] = mapped_column(String(120), default="")
    provider: Mapped[str] = mapped_column(String(40), default="")
    session_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    basket_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(Integer, default=None)
    # Raw LLM prompt/response, tool inputs/outputs — visible to the founder only.
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
