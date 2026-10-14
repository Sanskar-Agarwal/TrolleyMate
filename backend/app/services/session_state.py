"""Read helpers shared by agents and API routes."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import Basket, ConstraintSetRecord, Household, ShoppingRequest, ShoppingSession
from app.domain.enums import BasketStatus, RequestStatus


def household_of(db: Session, s: ShoppingSession) -> Household:
    return db.get(Household, s.household_id)


def active_constraints(db: Session, s: ShoppingSession) -> ConstraintSetRecord | None:
    return db.get(ConstraintSetRecord, s.active_constraint_set_id) if s.active_constraint_set_id else None


def latest_basket(db: Session, session_id: int) -> Basket | None:
    return db.scalar(
        select(Basket)
        .where(Basket.session_id == session_id, Basket.status != BasketStatus.superseded)
        .order_by(Basket.id.desc())
        .limit(1)
    )


def draft_request(db: Session, session_id: int) -> ShoppingRequest | None:
    return db.scalar(
        select(ShoppingRequest)
        .where(ShoppingRequest.session_id == session_id, ShoppingRequest.status == RequestStatus.draft)
        .order_by(ShoppingRequest.id.desc())
        .limit(1)
    )


def session_snapshot(db: Session, s: ShoppingSession) -> dict:
    household = household_of(db, s)
    cs = active_constraints(db, s)
    basket = latest_basket(db, s.id)
    draft = draft_request(db, s.id)
    return {
        "session_id": s.id,
        "goal": s.goal,
        "household": {
            "name": household.name,
            "size": household.size,
            "restrictions": [r["restriction"] for r in household.mandatory_restrictions()],
        },
        "active_constraints": cs.payload if cs else None,
        "has_basket": basket is not None,
        "basket_status": basket.status if basket else None,
        "pending_questions": draft.pending_questions if draft else [],
        "draft_stage": draft.stage if draft else None,
    }
