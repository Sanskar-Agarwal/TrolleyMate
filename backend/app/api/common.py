"""Helpers shared by every router: ownership checks, commit-and-return, serializers.

Routers return plain dicts built here. The matching TypeScript types live in
`frontend/src/api/types.ts` — keep the two in sync when you change a shape.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select

from app.agents.context import AgentContext
from app.domain import (
    AuditRecord,
    Basket,
    BasketItem,
    EscalationCase,
    Household,
    MealPlan,
    PriceQuote,
    ShoppingSession,
    Substitution,
    User,
)
from app.domain.enums import CaseStatus, UserRole
from app.services.pricing.normalisation import UnitPrice
from app.workflows.substitution import item_flags


def done(ctx: AgentContext, data: dict) -> dict:
    """Commit the request's transaction and attach the agent trace for the UI."""
    ctx.db.commit()
    return {**data, "trace": ctx.trace}


def not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found.")


def own_household(ctx: AgentContext) -> Household:
    if not ctx.user.households:
        raise not_found("Household")
    return ctx.user.households[0]


def own_session(ctx: AgentContext, session_id: int) -> ShoppingSession:
    s = ctx.db.get(ShoppingSession, session_id)
    if s is None or (s.shopper_id != ctx.user.id and ctx.user.role != UserRole.founder):
        raise not_found("Session")
    return s


def own_basket(ctx: AgentContext, basket_id: int) -> Basket:
    b = ctx.db.get(Basket, basket_id)
    if b is None:
        raise not_found("Basket")
    own_session(ctx, b.session_id)
    return b


def own_item(ctx: AgentContext, basket_id: int, item_id: int) -> BasketItem:
    b = own_basket(ctx, basket_id)
    item = next((i for i in b.items if i.id == item_id), None)
    if item is None:
        raise not_found("Basket item")
    return item


# --------------------------------------------------------------------------- serializers


def user_out(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "display_name": u.display_name, "role": u.role,
        "registration_no": u.registration_no, "specialisation": u.specialisation,
    }


def household_out(h: Household) -> dict:
    return {
        "id": h.id,
        "name": h.name,
        "region": h.region,
        "size": h.size,
        "members": [
            {
                "id": m.id, "name": m.name, "age_group": m.age_group,
                "restrictions": [{"id": p.id, "restriction": p.restriction, "kind": p.kind, "severity": p.severity} for p in m.dietary_profiles],
            }
            for m in h.members
        ],
        "preferences": [{"id": p.id, "kind": p.kind, "value": p.value, "source": p.source} for p in h.preferences],
        "mandatory_restrictions": h.mandatory_restrictions(),
    }


def item_out(i: BasketItem, quote: PriceQuote | None = None, flags: list[str] | None = None) -> dict:
    p = i.product
    unit = UnitPrice(quote.unit_price, quote.unit_basis).label() if quote and quote.unit_price is not None else None
    return {
        "id": i.id,
        "product": {
            "id": p.id, "name": p.name, "brand": p.brand, "category": p.category, "pack_size": p.pack_size,
            "unit": p.unit, "servings": p.servings, "tags": p.tags, "perishable": p.perishable,
        },
        "retailer": {"id": i.retailer.id, "name": i.retailer.name},
        "quantity": i.quantity,
        "pack_price": i.pack_price,
        "line_total": i.line_total,
        "unit_price_label": unit,
        "on_special": bool(quote.on_special) if quote else False,
        "compliance": i.compliance,
        "withheld": i.withheld,
        "rationale": i.rationale,
        "flags": flags or [],  # system reasons a substitute is due (UC-04 trigger)
    }


def basket_out(ctx: AgentContext, b: Basket) -> dict:
    quotes = {q.id: q for q in ctx.db.scalars(select(PriceQuote).where(PriceQuote.id.in_([i.quote_id for i in b.items if i.quote_id])))}
    cases = ctx.db.scalars(select(EscalationCase).where(EscalationCase.basket_id == b.id)).all()
    notes = b.notes or {}
    flags = item_flags(b, quotes)
    return {
        "id": b.id,
        "session_id": b.session_id,
        "status": b.status,
        "goal": b.goal,
        "total": b.total,
        "budget": b.budget,
        "remaining": round((b.budget or 0) - b.total, 2) if b.budget is not None else None,
        "items": [item_out(i, quotes.get(i.quote_id), flags.get(i.id)) for i in b.items],
        "summary": notes.get("summary"),
        "nutrition": ctx.compliance.current_nutrition(b) or notes.get("nutrition"),  # as the basket is now (1.2.11)
        "requirements": notes.get("requirements"),
        "metrics": notes.get("metrics"),
        "verdict": notes.get("verdict"),
        "excluded": notes.get("excluded", []),
        "notifications": notes.get("notifications", []),
        "strategy": (notes.get("facts") or {}).get("strategy"),
        "cases": [case_brief(c) for c in cases],
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }


def case_brief(c: EscalationCase) -> dict:
    return {
        "id": c.id, "status": c.status, "product": c.product.name, "reason": c.reason,
        "resolution": c.resolution, "assigned_to": c.assignee.display_name if c.assignee else None,
    }


def case_out(c: EscalationCase) -> dict:
    p = c.product
    return {
        **case_brief(c),
        "basket_id": c.basket_id,
        "basket_item_id": c.basket_item_id,
        "household_id": c.household_id,
        "requirements": c.requirements,
        "evidence": c.evidence,
        "thread": c.thread,
        "resolution_note": c.resolution_note,
        "product_detail": {
            "id": p.id, "name": p.name, "brand": p.brand, "ingredients": [i.name for i in p.ingredients],
            "may_contain": p.may_contain, "data_complete": p.data_complete, "category": p.category,
        },
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "assigned_at": c.assigned_at.isoformat() if c.assigned_at else None,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        "is_open": c.status != CaseStatus.resolved,
    }


def substitution_out(s: Substitution) -> dict:
    return {
        "id": s.id, "status": s.status, "reason": s.reason, "trade_off": s.trade_off, "facts": s.facts,
        "basket_item_id": s.basket_item_id,
        "original": {"id": s.original.id, "name": s.original.name},
        "replacement": {"id": s.replacement.id, "name": s.replacement.name} if s.replacement else None,
        "replacement_price": s.replacement_price,
    }


def meal_plan_out(m: MealPlan) -> dict:
    return {"id": m.id, "basket_id": m.basket_id, "summary": m.summary, **m.payload}


def audit_out(r: AuditRecord, *, full: bool) -> dict:
    out = {
        "id": r.id, "timestamp": r.timestamp.isoformat() if r.timestamp else None, "agent": r.agent, "action": r.action,
        "decision": r.decision, "rationale": r.rationale, "confidence": r.confidence, "model_version": r.model_version,
        "provider": r.provider, "session_id": r.session_id, "basket_id": r.basket_id,
    }
    if full:
        out["payload"] = r.payload
    return out
