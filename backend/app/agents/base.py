"""«abstract» Agent (class diagram). Every agent can perceive, think (LLM) and log."""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any

from app.core.tracing import operation
from app.llm import LLMResult

if TYPE_CHECKING:
    from app.agents.context import AgentContext
    from app.domain import AuditRecord, ShoppingSession


class Agent(ABC):
    role_name: str = "Agent"
    key: str = "agent"

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
        self.db = ctx.db
        self.llm = ctx.llm

    @property
    def model_version(self) -> str:
        return f"{self.llm.provider_name}:{self.llm.model_name}"

    def perceive(self, s: ShoppingSession) -> dict[str, Any]:
        """Snapshot of what the agent can see about a session (household, constraints, basket)."""
        from app.services.session_state import session_snapshot

        return session_snapshot(self.db, s)

    def think(self, task: str, context: dict) -> LLMResult:
        with operation("agent.think", {"agent.role": self.key}):
            return self.llm.run(task, context)

    def log(
        self,
        action: str,
        decision: str,
        *,
        rationale: str = "",
        confidence: float | None = None,
        session_id: int | None = None,
        basket_id: int | None = None,
        llm: LLMResult | None = None,
        payload: dict | None = None,
    ) -> AuditRecord:
        return self.ctx.manager.record(
            agent=self.role_name,
            agent_key=self.key,
            action=action,
            decision=decision,
            rationale=rationale,
            confidence=confidence,
            session_id=session_id,
            basket_id=basket_id,
            llm=llm,
            payload=payload or {},
        )
