"""Domain::RequestsConstraints — ShoppingSession, ShoppingRequest, ConstraintSet, Constraint subtypes.

The constraint *hierarchy* (Constraint, BudgetConstraint, ...) is implemented as
plain Python classes built from the stored payload, so the class diagram's
operations (`isHard`, `violatedBy`, `hardConstraints`, `isSatisfiedBy`) are real
methods, while the database stores one JSON payload per versioned set.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.domain.enums import (
    InputMode,
    IntakeStage,
    OptimisationGoal,
    RequestStatus,
    SessionStatus,
    Severity,
)

if TYPE_CHECKING:
    pass


class ShoppingSession(Base):
    __tablename__ = "shopping_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    shopper_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id"))
    goal: Mapped[str] = mapped_column(String(30), default=OptimisationGoal.balanced)
    status: Mapped[str] = mapped_column(String(30), default=SessionStatus.open)
    # Plain integer (not an FK) to avoid a circular FK with constraint_sets.
    active_constraint_set_id: Mapped[int | None] = mapped_column(Integer, default=None)
    # Swaps the shopper declined in this session (1.2.5): list of [original_id, replacement_id].
    rejected_swaps: Mapped[list] = mapped_column(JSON, default=list)
    chat_history: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    requests: Mapped[list[ShoppingRequest]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ShoppingRequest.id"
    )

    def activate(self, cs: ConstraintSetRecord) -> None:
        self.active_constraint_set_id = cs.id


class ShoppingRequest(Base):
    __tablename__ = "shopping_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("shopping_sessions.id"))
    raw_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=RequestStatus.draft)
    stage: Mapped[str] = mapped_column(String(40), default=IntakeStage.awaiting_confirmation)
    mode: Mapped[str] = mapped_column(String(10), default=InputMode.text)
    correction_count: Mapped[int] = mapped_column(Integer, default=0)
    # Clarifying Q&A — these do NOT count as corrections (Activity 7.1 note).
    clarifications: Mapped[list] = mapped_column(JSON, default=list)
    pending_questions: Mapped[list] = mapped_column(JSON, default=list)
    draft_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    session: Mapped[ShoppingSession] = relationship(back_populates="requests")

    def confirm(self) -> None:
        self.status = RequestStatus.confirmed
        self.stage = IntakeStage.ended

    def mark_infeasible(self) -> None:
        self.status = RequestStatus.infeasible


class ConstraintSetRecord(Base):
    """A versioned, confirmed (or draft) set of constraints. Payload schema: ConstraintPayload."""

    __tablename__ = "constraint_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("shopping_sessions.id"))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("shopping_requests.id"), default=None)
    version: Mapped[int] = mapped_column(Integer, default=1)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    origin: Mapped[str] = mapped_column(String(30), default="intake")  # intake | negotiation | edit

    def to_constraint_set(self) -> ConstraintSet:
        return ConstraintSet.from_payload(self.payload, version=self.version)


# --------------------------------------------------------------------------
# Constraint hierarchy (class diagram: Constraint {abstract} and subtypes)
# --------------------------------------------------------------------------


@dataclass
class BasketView:
    """The numbers a constraint needs to judge a basket. Built by the optimiser/agents."""

    total: float
    nutrition: dict[str, float]  # kcal, protein_g, veg_serves, fibre_g
    flagged_restrictions: set[str]  # restrictions any item violates


class Constraint(ABC):
    priority: int = 1
    relaxable: bool = True

    def is_hard(self) -> bool:
        return not self.relaxable

    @abstractmethod
    def violated_by(self, b: BasketView) -> bool: ...

    @abstractmethod
    def describe(self) -> str: ...


@dataclass
class BudgetConstraint(Constraint):
    limit: float
    priority: int = 1
    relaxable: bool = True  # negotiable via UC-03

    def violated_by(self, b: BasketView) -> bool:
        return b.total > self.limit + 1e-6

    def describe(self) -> str:
        return f"Spend at most ${self.limit:.2f}"


@dataclass
class DietaryConstraint(Constraint):
    restriction: str
    severity: str = Severity.severe
    priority: int = 0
    relaxable: bool = False  # {relaxable = false} in the class diagram — never traded away

    def violated_by(self, b: BasketView) -> bool:
        return self.restriction in b.flagged_restrictions

    def describe(self) -> str:
        return f"No {self.restriction.replace('_', ' ')} ({self.severity})"


@dataclass
class MealCountConstraint(Constraint):
    meals_per_day: float
    days: int
    household_size: int
    priority: int = 1
    relaxable: bool = True

    @property
    def person_meals(self) -> int:
        return int(round(self.meals_per_day * self.days * self.household_size))

    def violated_by(self, b: BasketView) -> bool:  # coverage is enforced by the solver
        return False

    def describe(self) -> str:
        return (
            f"{self.meals_per_day:g} meals/day for {self.days} days, "
            f"{self.household_size} {'person' if self.household_size == 1 else 'people'}"
        )


@dataclass
class NutritionalConstraint(Constraint):
    nutrient: str
    minimum_per_day: float  # per person
    person_days: float = 1.0
    priority: int = 2
    relaxable: bool = True

    def violated_by(self, b: BasketView) -> bool:
        return b.nutrition.get(self.nutrient, 0.0) + 1e-6 < self.minimum_per_day * self.person_days

    def describe(self) -> str:
        return f"At least {self.minimum_per_day:g} {self.nutrient.replace('_', ' ')} per person per day"


@dataclass
class ConstraintSet:
    version: int
    constraints: list[Constraint]
    payload: dict

    @classmethod
    def from_payload(cls, payload: dict, version: int = 1) -> ConstraintSet:
        items: list[Constraint] = []
        size = int(payload.get("household_size") or 1)
        if payload.get("budget") is not None:
            items.append(BudgetConstraint(limit=float(payload["budget"])))
        for r in payload.get("restrictions", []):
            items.append(DietaryConstraint(restriction=r["restriction"], severity=r.get("severity", "severe")))
        meal = None
        if payload.get("meals_per_day") and payload.get("days"):
            meal = MealCountConstraint(
                meals_per_day=float(payload["meals_per_day"]),
                days=int(payload["days"]),
                household_size=size,
            )
            items.append(meal)
        person_days = (meal.days * size) if meal else size
        for t in payload.get("nutritional_targets", []):
            items.append(
                NutritionalConstraint(
                    nutrient=t["nutrient"], minimum_per_day=float(t["minimum_per_day"]), person_days=person_days
                )
            )
        return cls(version=version, constraints=items, payload=payload)

    def hard_constraints(self) -> list[Constraint]:
        return [c for c in self.constraints if c.is_hard()]

    def is_satisfied_by(self, b: BasketView) -> bool:
        return not any(c.violated_by(b) for c in self.constraints)

    def violations(self, b: BasketView) -> list[str]:
        return [c.describe() for c in self.constraints if c.violated_by(b)]

    @property
    def budget(self) -> BudgetConstraint | None:
        return next((c for c in self.constraints if isinstance(c, BudgetConstraint)), None)

    @property
    def meal_count(self) -> MealCountConstraint | None:
        return next((c for c in self.constraints if isinstance(c, MealCountConstraint)), None)

    @property
    def dietary(self) -> list[DietaryConstraint]:
        return [c for c in self.constraints if isinstance(c, DietaryConstraint)]

    @property
    def nutritional(self) -> list[NutritionalConstraint]:
        return [c for c in self.constraints if isinstance(c, NutritionalConstraint)]
