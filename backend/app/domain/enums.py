"""Enumerations from the Stage 1 class model (Figure 5) and state machines (Section 9)."""

from enum import StrEnum


class UserRole(StrEnum):
    shopper = "shopper"
    dietitian = "dietitian"
    founder = "founder"


class OptimisationGoal(StrEnum):
    lowest_cost = "lowest_cost"
    best_nutrition = "best_nutrition"
    least_waste = "least_waste"
    fastest_cook = "fastest_cook"
    balanced = "balanced"


class SessionStatus(StrEnum):
    open = "open"
    optimising = "optimising"
    basket_ready = "basket_ready"
    closed = "closed"


class RequestStatus(StrEnum):
    """State machine 9.1. Detailed intake states are substates of `draft`."""

    draft = "draft"
    confirmed = "confirmed"
    cancelled = "cancelled"
    infeasible = "infeasible"


class IntakeStage(StrEnum):
    """Substates of RequestStatus.draft (State machine 9.1)."""

    awaiting_clarification = "awaiting_clarification"
    awaiting_form = "awaiting_form"
    awaiting_confirmation = "awaiting_confirmation"
    awaiting_save_decision = "awaiting_save_decision"
    ended = "ended"


class InputMode(StrEnum):
    text = "text"
    form = "form"


class BasketStatus(StrEnum):
    optimised = "optimised"  # produced by the solver, not yet verified
    verified = "verified"  # passed compliance; ready for shopper review
    pending_review = "pending_review"  # one or more items withheld for a dietitian
    accepted = "accepted"  # the shopper accepted it
    superseded = "superseded"  # replaced by a newer basket in the session


class ItemCompliance(StrEnum):
    unchecked = "unchecked"
    compliant = "compliant"
    violation = "violation"
    uncertain = "uncertain"


class SubReason(StrEnum):
    user_requested = "user_requested"
    out_of_stock = "out_of_stock"
    over_budget = "over_budget"
    cheaper = "cheaper"
    failed_review = "failed_review"


class SubStatus(StrEnum):
    """State machine 9.2."""

    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    discarded = "discarded"


class QuoteStatus(StrEnum):
    """State machine 9.3."""

    fresh = "fresh"
    stale = "stale"
    unavailable = "unavailable"
    superseded = "superseded"


class VerdictStatus(StrEnum):
    """State machine 9.4 outcomes."""

    pending = "pending"
    passed = "passed"
    failed = "failed"
    escalated = "escalated"


class CaseStatus(StrEnum):
    """State machine 9.5. `awaiting_information` is a substate of under_review."""

    open = "open"
    assigned = "assigned"
    under_review = "under_review"
    awaiting_information = "awaiting_information"
    resolved = "resolved"


class Severity(StrEnum):
    severe = "severe"  # anaphylaxis-level; never relaxed
    moderate = "moderate"  # intolerance; never relaxed
    mild = "mild"
    preference = "preference"  # soft; can be traded away


class RestrictionKind(StrEnum):
    allergy = "allergy"
    intolerance = "intolerance"
    diet = "diet"
