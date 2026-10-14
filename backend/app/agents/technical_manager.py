"""«governance» TechnicalManagerAgent — audit log, explanations, policy (1.2.14, UC-07).

Deliberately outside the supervisor–worker chain: every agent writes its decisions
through `record`, and explanations are generated only from what was recorded.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.agents.base import Agent
from app.core.config import get_settings
from app.domain import AuditRecord, Basket, BasketItem, User
from app.domain.enums import UserRole
from app.llm import LLMResult

UNAVAILABLE = "Reasoning unavailable for this recommendation."


class TechnicalManagerAgent(Agent):
    role_name = "AI Technical Manager"
    key = "technical_manager"

    # --- Audit -------------------------------------------------------------

    def record(
        self,
        *,
        agent: str,
        agent_key: str,
        action: str,
        decision: str,
        rationale: str = "",
        confidence: float | None = None,
        session_id: int | None = None,
        basket_id: int | None = None,
        llm: LLMResult | None = None,
        payload: dict | None = None,
    ) -> AuditRecord:
        data = dict(payload or {})
        if llm is not None:
            data["llm"] = {
                "provider": llm.provider,
                "model": llm.model,
                "fell_back": llm.fell_back,
                "latency_ms": llm.latency_ms,
                "error": llm.error,
                "prompt": llm.prompt,
                "raw": (llm.raw or "")[:4000],
            }
        record = AuditRecord(
            agent=agent,
            action=action,
            decision=decision,
            rationale=rationale,
            confidence=confidence,
            model_version=llm.model_version if llm else "deterministic",
            provider=llm.provider if llm else "deterministic",
            session_id=session_id,
            basket_id=basket_id,
            actor_user_id=self.ctx.user.id if self.ctx.user else None,
            payload=data,
        )
        self.db.add(record)
        self.db.flush()
        self.ctx.trace.append(
            {
                "id": record.id,
                "agent": agent_key,
                "agent_name": agent,
                "action": action,
                "decision": decision,
                "confidence": confidence,
                "provider": record.provider,
                "fell_back": bool(llm and llm.fell_back),
                "llm": llm is not None,
                "at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        return record

    # --- Explanations ------------------------------------------------------

    def explain_for(self, b: Basket) -> dict:
        facts = (b.notes or {}).get("facts")
        has_trail = self.db.scalar(select(AuditRecord.id).where(AuditRecord.basket_id == b.id).limit(1))
        if not facts or not has_trail:
            return {"available": False, "text": UNAVAILABLE, "facts": None}
        result = self.think("explain", {"scope": "basket", "facts": facts})
        self.log("explain_basket", result.data[:300], basket_id=b.id, session_id=b.session_id, llm=result)
        return {"available": True, "text": result.data, "facts": facts}

    def explain_item(self, item: BasketItem) -> dict:
        if not item.rationale:
            return {"available": False, "text": UNAVAILABLE, "facts": None}
        facts = {
            "item": item.product.name,
            "role": item.product.category,
            "reason": item.rationale,
            "retailer": item.retailer.name,
            "pack_price": item.pack_price,
            "quantity": item.quantity,
            "compliance": item.compliance,
            "alternatives": (item.basket.notes or {}).get("alternatives", {}).get(str(item.product_id), []),
        }
        result = self.think("explain", {"scope": "item", "facts": facts})
        self.log("explain_item", result.data[:300], basket_id=item.basket_id, llm=result)
        return {"available": True, "text": result.data, "facts": facts}

    # --- Policy & permissions ---------------------------------------------

    def policy(self) -> dict:
        s = get_settings()
        return {
            "safety_threshold": s.compliance_safety_threshold,
            "max_corrections": s.max_corrections,
            "price_max_age_hours": s.price_max_age_hours,
            "review_sla_minutes": s.review_sla_minutes,
            "mandatory_restrictions_relaxable": False,
        }

    @staticmethod
    def can_review(user: User) -> bool:
        return user.role in (UserRole.dietitian, UserRole.founder)
