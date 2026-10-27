"""«governance» TechnicalManagerAgent — audit log, explanations, policy (1.2.14, UC-07).

Deliberately outside the supervisor–worker chain: every agent writes its decisions
through `record`, and explanations are generated only from what was recorded.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.agents.base import Agent
from app.core.config import get_settings
from app.domain import AuditRecord, Basket, BasketItem, ComplianceVerdict, ConstraintSetRecord, PriceQuote, User
from app.domain.enums import UserRole
from app.llm import LLMResult

UNAVAILABLE = "Reasoning unavailable for this recommendation."
# What an explanation may cite. Anything missing is named, never filled in (1.2.14).
EVIDENCE_KINDS = ("constraints", "prices", "verdict", "tools", "audit_trail")


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

    def basket_evidence(self, b: Basket) -> dict:
        """The recorded inputs behind a basket: confirmed constraints, the price quotes used,
        the solver's results, the compliance verdict, and the agent decisions logged for it."""
        cs = self.db.get(ConstraintSetRecord, b.constraint_set_id) if b.constraint_set_id else None
        verdict = self.db.scalar(
            select(ComplianceVerdict).where(ComplianceVerdict.basket_id == b.id).order_by(ComplianceVerdict.id.desc()).limit(1)
        )
        quote_ids = [i.quote_id for i in b.items if i.quote_id]
        quotes = {q.id: q for q in self.db.scalars(select(PriceQuote).where(PriceQuote.id.in_(quote_ids)))} if quote_ids else {}
        trail = self.db.scalars(select(AuditRecord).where(AuditRecord.basket_id == b.id).order_by(AuditRecord.id)).all()
        notes = b.notes or {}
        priced = []
        for i in b.items:
            q = quotes.get(i.quote_id)
            if q is not None:
                priced.append({
                    "item": i.product.name, "retailer": i.retailer.name, "price": q.price, "quote_id": q.id,
                    "captured_at": q.captured_at.isoformat(timespec="minutes"), "source": getattr(q, "source_type", None),
                })
        evidence = {
            "constraints": {
                "version": cs.version, "budget": cs.payload.get("budget"), "days": cs.payload.get("days"),
                "meals_per_day": cs.payload.get("meals_per_day"), "household_size": cs.payload.get("household_size"),
                "restrictions": [r["restriction"] for r in cs.payload.get("restrictions", [])],
            } if cs and cs.confirmed_at else None,
            "prices": priced or None,
            "unpriced_items": [i.product.name for i in b.items if i.quote_id not in quotes],
            "verdict": {
                "id": verdict.id, "status": verdict.status, "confidence": verdict.confidence, "source": verdict.source,
            } if verdict else None,
            "tools": {"solver": notes.get("metrics"), "solver_ms": notes.get("solver_ms")} if notes.get("metrics") else None,
            "audit_trail": [{"id": r.id, "agent": r.agent, "action": r.action} for r in trail] or None,
        }
        evidence["missing"] = [k for k in EVIDENCE_KINDS if not evidence[k]]
        return evidence

    def explain_for(self, b: Basket) -> dict:
        facts = (b.notes or {}).get("facts")
        evidence = self.basket_evidence(b)
        if not facts or not evidence["audit_trail"]:
            return {"available": False, "text": UNAVAILABLE, "facts": None, "evidence": evidence}
        grounded = {
            **facts,
            "constraint_version": (evidence["constraints"] or {}).get("version"),
            "verdict": evidence["verdict"],
            "evidence_missing": evidence["missing"],
        }
        result = self.think("explain", {"scope": "basket", "facts": grounded})
        self.log("explain_basket", result.data[:300], basket_id=b.id, session_id=b.session_id, llm=result,
                 payload={"evidence_missing": evidence["missing"]})
        return {"available": True, "text": result.data, "facts": grounded, "evidence": evidence}

    def explain_item(self, item: BasketItem) -> dict:
        if not item.rationale:
            return {"available": False, "text": UNAVAILABLE, "facts": None, "evidence": None}
        quote = self.db.get(PriceQuote, item.quote_id) if item.quote_id else None
        verdict = self.db.scalar(
            select(ComplianceVerdict).where(ComplianceVerdict.basket_id == item.basket_id).order_by(ComplianceVerdict.id.desc()).limit(1)
        )
        products = ((verdict.evidence or {}).get("products") or []) if verdict else []
        finding = next((p for p in products if p.get("product_id") == item.product_id), None)
        evidence = {
            "price": {
                "retailer": item.retailer.name, "price": quote.price, "quote_id": quote.id,
                "captured_at": quote.captured_at.isoformat(timespec="minutes"),
            } if quote else None,
            "compliance": {
                "status": finding.get("status"), "confidence": finding.get("confidence"),
                "findings": [f.get("detail") for f in finding.get("findings", [])],
            } if finding else None,
        }
        evidence["missing"] = [k for k in ("price", "compliance") if not evidence[k]]
        facts = {
            "item": item.product.name,
            "role": item.product.category,
            "reason": item.rationale,
            "retailer": item.retailer.name,
            "pack_price": item.pack_price,
            "quantity": item.quantity,
            "compliance": item.compliance,
            "alternatives": (item.basket.notes or {}).get("alternatives", {}).get(str(item.product_id), []),
            "price_captured_at": (evidence["price"] or {}).get("captured_at"),
            "compliance_findings": (evidence["compliance"] or {}).get("findings"),
            "evidence_missing": evidence["missing"],
        }
        result = self.think("explain", {"scope": "item", "facts": facts})
        self.log("explain_item", result.data[:300], basket_id=item.basket_id, llm=result)
        return {"available": True, "text": result.data, "facts": facts, "evidence": evidence}

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
