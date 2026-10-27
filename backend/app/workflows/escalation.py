"""UC-06 extension — human review of escalated compliance cases (Activity 7.5, Sequence 8.5,
State machine 9.5). Owner: Governance.

    open ──assignTo(d)[authorised]──▶ assigned ──beginReview()──▶ under_review ⇄ awaiting_information
      ▲                                  │                              │
      └──── after(review SLA) ───────────┘                       resolve(v) ▼
                                                                       resolved
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.core.config import get_settings
from app.domain import Basket, BasketItem, ComplianceVerdict, EscalationCase, Household, User
from app.domain.enums import BasketStatus, CaseStatus, ItemCompliance, UserRole, VerdictStatus


class EscalationError(ValueError):
    pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def raise_case(agent, verdict: ComplianceVerdict, item: BasketItem, household: Household, finding, restrictions: list[dict]) -> EscalationCase:
    """Step 1–3: record the case, queue it, and try to assign an authorised dietitian.
    Re-uses an open case for the same product and household instead of duplicating it."""
    db = agent.db
    existing = db.scalar(
        select(EscalationCase).where(
            EscalationCase.product_id == item.product_id,
            EscalationCase.household_id == household.id,
            EscalationCase.status != CaseStatus.resolved,
        )
    )
    if existing:
        existing.basket_id, existing.basket_item_id, existing.verdict_id = item.basket_id, item.id, verdict.id
        return existing

    case = EscalationCase(
        verdict_id=verdict.id, basket_id=item.basket_id, household_id=household.id, basket_item_id=item.id,
        product_id=item.product_id,
        reason="; ".join(f["detail"] for f in finding.findings) or "Compliance could not be confirmed",
        requirements=restrictions,
        evidence={"confidence": finding.confidence, "findings": finding.findings, "household": household.name},
        thread=[],
    )
    db.add(case)
    db.flush()
    agent.log(
        "raise_escalation",
        f"Case #{case.id}: {item.product.name} withheld pending human review",
        rationale=case.reason, confidence=finding.confidence, basket_id=item.basket_id,
    )
    assign(agent, case)
    return case


def assign(agent, case: EscalationCase, reviewer: User | None = None) -> EscalationCase:
    """assignTo(d) [d is authorised]; picks the least-loaded dietitian if none given (ext 3a/3c)."""
    db = agent.db
    if reviewer is None:
        load = (
            select(User, func.count(EscalationCase.id))
            .outerjoin(EscalationCase, (EscalationCase.assigned_to_id == User.id) & (EscalationCase.status != CaseStatus.resolved))
            .where(User.role == UserRole.dietitian)
            .group_by(User.id)
            .order_by(func.count(EscalationCase.id), User.id)
        )
        row = db.execute(load).first()
        if row is None:
            return case  # ext 3a: no dietitian → stays open; founder can pick it up
        reviewer = row[0]
    if not agent.ctx.manager.can_review(reviewer):
        raise EscalationError(f"{reviewer.display_name} is not an authorised reviewer.")  # ext 3c
    case.assigned_to_id, case.assigned_at, case.status = reviewer.id, datetime.now(), CaseStatus.assigned
    agent.log("assign_reviewer", f"Case #{case.id} assigned to {reviewer.display_name}", basket_id=case.basket_id)
    return case


def sweep_sla(agent) -> int:
    """after(review SLA)[review not started] / release reviewer (ext 3b). Called when the queue is read."""
    cutoff = datetime.now() - timedelta(minutes=get_settings().review_sla_minutes)
    stale = agent.db.scalars(
        select(EscalationCase).where(EscalationCase.status == CaseStatus.assigned, EscalationCase.assigned_at < cutoff)
    ).all()
    for case in stale:
        case.status, case.assigned_to_id, case.assigned_at = CaseStatus.open, None, None
        agent.log("release_reviewer", f"Case #{case.id} returned to queue (review SLA expired)", basket_id=case.basket_id)
    return len(stale)


def _check_reviewer(case: EscalationCase, user: User) -> None:
    if user.role == UserRole.founder:
        return  # founder exception queue fallback
    if case.assigned_to_id != user.id:
        raise EscalationError("This case is assigned to another reviewer.")


def begin_review(agent, case: EscalationCase, user: User) -> EscalationCase:
    if case.status == CaseStatus.open and user.role in (UserRole.dietitian, UserRole.founder):
        assign(agent, case, user)
    _check_reviewer(case, user)
    if case.status != CaseStatus.assigned:
        raise EscalationError(f"Case is {case.status}; only assigned cases can start review.")
    case.status, case.review_started_at = CaseStatus.under_review, datetime.now()
    agent.log("begin_review", f"{user.display_name} started reviewing case #{case.id}", basket_id=case.basket_id)
    return case


def request_information(agent, case: EscalationCase, user: User, question: str) -> EscalationCase:
    """requestInformation(q) → the compliance agent supplies what it can (ext 5a)."""
    _check_reviewer(case, user)
    if case.status != CaseStatus.under_review:
        raise EscalationError("Start the review before requesting information.")
    case.status = CaseStatus.awaiting_information
    thread = list(case.thread) + [{"from": "reviewer", "author": user.display_name, "text": question, "at": _now()}]
    answer = agent.ctx.compliance.supply_information(case, question)
    thread.append({"from": "agent", "author": "AI Nutrition & Compliance", "text": answer, "at": _now()})
    case.thread = thread  # reassign so SQLAlchemy sees the JSON change
    case.status = CaseStatus.under_review  # supplyInformation(e)
    return case


def resolve(agent, case: EscalationCase, user: User, decision: str, note: str = "") -> EscalationCase:
    """resolve(v): record the human verdict, audit it, and apply it to the withheld item (steps 6–8)."""
    _check_reviewer(case, user)
    if case.status not in (CaseStatus.under_review, CaseStatus.awaiting_information):
        raise EscalationError("Start the review before recording a decision.")
    if decision not in (VerdictStatus.passed, VerdictStatus.failed):
        raise EscalationError("Decision must be 'passed' or 'failed'.")
    db = agent.db
    human = ComplianceVerdict(
        basket_id=case.basket_id, status=decision, confidence=1.0, source="human", reviewer_id=user.id,
        evidence={"case_id": case.id, "note": note},
    )
    db.add(human)
    case.status, case.resolution, case.resolution_note, case.resolved_at = CaseStatus.resolved, decision, note, datetime.now()
    agent.ctx.manager.record(
        agent=f"Dietitian ({user.display_name})", agent_key="human_reviewer", action="resolve_escalation",
        decision=f"Case #{case.id} {decision}: {case.product.name}", rationale=note, confidence=1.0, basket_id=case.basket_id,
    )
    _apply(agent, case, decision)
    return case


def _apply(agent, case: EscalationCase, decision: str) -> None:
    db = agent.db
    item = db.get(BasketItem, case.basket_item_id) if case.basket_item_id else None
    basket = db.get(Basket, case.basket_id)
    if item is None or basket is None or basket.status == BasketStatus.superseded:
        return
    name = item.product.name
    # The "held" notice and withheld fact no longer apply once a dietitian has decided.
    notes = dict(basket.notes or {})
    notes["notifications"] = [n for n in notes.get("notifications", []) if not n.startswith(f"{name} is held")]
    facts = dict(notes.get("facts") or {})
    facts["withheld"] = [w for w in facts.get("withheld", []) if w != name]
    if decision == VerdictStatus.passed:
        item.withheld, item.compliance = False, ItemCompliance.compliant
        notes["notifications"].append(f"{name} was confirmed safe by a dietitian and added back to your basket.")
        notes["facts"] = facts
        basket.notes = notes
        agent.log("release_item", f"{name} released to the basket after review", basket_id=basket.id)
    else:
        case.basket_item_id = None
        basket.items.remove(item)
        db.flush()
        facts["items"] = [i for i in facts.get("items", []) if i.get("name") != name]
        notes["facts"] = facts
        notes["notifications"].append(f"{name} was removed after dietitian review. Ask for a substitute if you need a replacement.")
        basket.notes = notes
        agent.log("exclude_item", f"{name} excluded from the basket after review", basket_id=basket.id)
    basket.recalc_total()
    if basket.notes and "facts" in basket.notes:
        basket.notes = {**basket.notes, "facts": {**basket.notes["facts"], "total": basket.total}}
    if not any(i.withheld for i in basket.items) and basket.status == BasketStatus.pending_review:
        basket.status = BasketStatus.verified
