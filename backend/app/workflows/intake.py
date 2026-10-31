"""UC-01 — Natural-language intake & constraint confirmation (Activity 7.1, Sequence 8.1,
State machine 9.1). Owner: Intake & Optimisation.

Draft constraints never become active until `confirm` commits them atomically.
Clarification answers do not count as corrections; the third correction switches
the request to a structured form. Household mandatory restrictions can never be
removed from a draft.
"""

from __future__ import annotations

import math
import re
from datetime import datetime

from sqlalchemy import func, select

from app.core.config import get_settings
from app.domain import ConstraintSetRecord, ShoppingRequest, ShoppingSession
from app.domain.enums import InputMode, IntakeStage, OptimisationGoal, RequestStatus, Severity
from app.optimisation.types import normalise_nutrient
from app.services.dietary_rules import RESTRICTION_RULES, label, normalise_restriction
from app.services.session_state import household_of

REQUIRED = ("budget", "household_size", "meals_per_day", "days")
# Share of an adult serve each age group eats (Australian Guide to Healthy Eating, rounded).
PORTION_FACTORS = {"child": 0.6, "teen": 1.0, "adult": 1.0, "senior": 0.85}
QUESTIONS = {
    "budget": "What's your budget for this shop?",
    "household_size": "How many people are you shopping for?",
    "meals_per_day": "Which meals should I cover each day: dinner only, lunch and dinner, or all three?",
    "days": "How many days should this shop last?",
}


class IntakeError(ValueError):
    pass


# --------------------------------------------------------------------------- helpers


def _merge(draft: dict, extracted: dict) -> dict:
    """Fields present in `extracted` override the draft; lists are unioned."""
    out = dict(draft)
    for key in REQUIRED + ("goal_hint",):
        if extracted.get(key) is not None:
            out[key] = extracted[key]
    for ambiguity in extracted.get("ambiguities", []):
        field = ambiguity["field"]
        if field in REQUIRED and extracted.get(field) is None:
            out[field] = None
        elif field == "nutritional_targets" and not extracted.get(field):
            out[field] = []
    removed = {normalise_restriction(r) for r in extracted.get("removed_restrictions", [])}
    restrictions = {r["restriction"]: r for r in out.get("restrictions", []) if r["restriction"] not in removed}
    for r in extracted.get("restrictions", []):
        rid = normalise_restriction(r["restriction"])
        restrictions[rid] = {"restriction": rid, "severity": r.get("severity", "severe"), "source": "request", "label": label(rid)}
    out["restrictions"] = list(restrictions.values())
    targets = {t["nutrient"]: t for t in out.get("nutritional_targets", [])}
    for t in extracted.get("nutritional_targets", []):
        targets[t["nutrient"]] = {"nutrient": t["nutrient"], "minimum_per_day": float(t["minimum_per_day"])}
    out["nutritional_targets"] = list(targets.values())
    removed_prefs = set(extracted.get("removed_preferences", []))
    out["preferences"] = sorted((set(out.get("preferences", [])) - removed_prefs) | set(extracted.get("preferences", [])))
    if removed_prefs:
        out["preferences_override"] = True
    # A new ambiguous request needs a fresh answer even if an older target was declined.
    out["answered"] = sorted(set(out.get("answered", [])) - {a["field"] for a in extracted.get("ambiguities", [])})
    _validate_values(out)
    return out


def _apply_household(session: ShoppingSession, draft: dict, db) -> dict:
    household = household_of(db, session)
    out = dict(draft)
    assumptions = [note for note in out.get("assumptions", [])
                   if not note.startswith("Portions sized for your household's ages (")
                   and not (note.startswith("Shopping for ") and note.endswith("(from your household profile).")
                            and out.get("household_size") != household.size)]
    if out.get("household_size") is None and household.members:
        out["household_size"] = household.size
        note = f"Shopping for {household.size} (from your household profile)."
        if note not in assumptions:
            assumptions.append(note)
    # Portions follow the profile only when shopping for exactly that household.
    out.pop("portions", None)
    if household.members and out.get("household_size") == household.size:
        portions = round(sum(PORTION_FACTORS.get(m.age_group, 1.0) for m in household.members), 2)
        if portions != household.size:
            out["portions"] = portions
            note = f"Portions sized for your household's ages ({portions:g} adult serves per meal)."
            if note not in assumptions:
                assumptions.append(note)
    restrictions = {r["restriction"]: r for r in out.get("restrictions", [])}
    for r in household.mandatory_restrictions():
        restrictions[r["restriction"]] = {**r, "label": label(r["restriction"]), "locked": True}
    out["restrictions"] = list(restrictions.values())
    targets = {}
    for t in out.get("nutritional_targets", []):
        nutrient = normalise_nutrient(t["nutrient"])
        if nutrient is None:
            note = f"I can't check {t['nutrient'].replace('_', ' ')} from product data yet, so that target isn't part of this shop."
            if note not in assumptions:
                assumptions.append(note)
            continue
        targets[nutrient] = {**t, "nutrient": nutrient}
    out["nutritional_targets"] = list(targets.values())
    saved_prefs = set() if out.get("preferences_override") else {f"{p.kind}:{p.value}" for p in household.preferences}
    out["preferences"] = sorted(set(out.get("preferences", [])) | saved_prefs)
    out["assumptions"] = assumptions
    return out


def _questions(draft: dict, ambiguities: list[dict]) -> list[dict]:
    qs = [{"field": f, "question": QUESTIONS[f]} for f in REQUIRED if draft.get(f) in (None, 0)]
    answered = set(draft.get("answered", []))
    for a in ambiguities:
        if a["field"] not in answered and not any(q["field"] == a["field"] for q in qs):
            if a["field"] == "nutritional_targets" and draft.get("nutritional_targets"):
                continue
            qs.append({"field": a["field"], "question": a["question"]})
    return qs


def _still_open(pending: list[dict], draft: dict) -> list[dict]:
    """Clarifying questions not answered by the latest draft (required fields are re-derived by _questions)."""
    return [q for q in pending if q["field"] not in REQUIRED and draft.get(q["field"]) in (None, 0, [])]


def _stage_after_update(req: ShoppingRequest) -> None:
    if req.pending_questions:
        req.stage = IntakeStage.awaiting_clarification
    elif req.mode == InputMode.form:
        req.stage = IntakeStage.awaiting_form
    else:
        req.stage = IntakeStage.awaiting_confirmation


def _household_context(session: ShoppingSession, db) -> dict:
    h = household_of(db, session)
    return {"size": h.size, "restrictions": [r["restriction"] for r in h.mandatory_restrictions()]}


def _summary(draft: dict) -> str:
    parts = []
    if draft.get("budget") is not None:
        parts.append(f"${draft['budget']:g}")
    if draft.get("meals_per_day") and draft.get("days"):
        parts.append(f"{draft['meals_per_day']:g} meals/day × {draft['days']} days")
    if draft.get("household_size"):
        parts.append(f"{draft['household_size']} people")
    if draft.get("restrictions"):
        parts.append("no " + ", ".join(r["restriction"].replace("_", " ") for r in draft["restrictions"]))
    return "; ".join(parts) or "nothing extracted yet"


# --------------------------------------------------------------------------- operations


def start(agent, session: ShoppingSession, text: str) -> ShoppingRequest:
    db = agent.db
    for old in session.requests:
        if old.status == RequestStatus.draft:
            old.status, old.stage = RequestStatus.cancelled, IntakeStage.ended

    req = ShoppingRequest(raw_text=text)
    session.requests.append(req)  # via the collection, so session.requests stays current
    db.flush()
    result = agent.think("extract_constraints", {"text": text, "household": _household_context(session, db)})
    data = result.data

    if not data.get("interpretation_ok", True):
        req.mode, req.stage = InputMode.form, IntakeStage.awaiting_form
        req.draft_payload = _apply_household(session, {}, db)
        req.pending_questions = []
        agent.log("extract_constraints", "Could not interpret the request; offered the structured form",
                  session_id=session.id, llm=result, confidence=0.2)
        return req

    draft = _apply_household(session, _merge({}, data), db)
    req.draft_payload = draft
    req.pending_questions = _questions(draft, data.get("ambiguities", []))
    _stage_after_update(req)
    agent.log(
        "extract_constraints", f"Interpreted: {_summary(draft)}",
        rationale=f"{len(req.pending_questions)} question(s) outstanding" if req.pending_questions else "Ready for confirmation",
        confidence=0.6 if req.pending_questions else 0.9, session_id=session.id, llm=result,
        payload={"raw_text": text, "draft": draft},
    )
    return req


def clarify(agent, req: ShoppingRequest, answer: str) -> ShoppingRequest:
    _ensure_draft(req)
    if req.mode == InputMode.form:
        raise IntakeError("Please edit your details directly in the form, then save and confirm them.")
    session = req.session
    pending = [q["field"] for q in req.pending_questions]
    result = agent.think(
        "extract_constraints",
        {"text": answer, "draft": req.draft_payload, "pending_fields": pending, "household": _household_context(session, agent.db)},
    )
    draft = _merge(req.draft_payload, result.data)
    declined = bool(re.fullmatch(
        r"\s*(?:no(?: thanks| target)?|none|skip(?: (?:it|that|the target))?|not sure|"
        r"(?:i )?(?:don't|do not|dont) (?:know|have a target|want (?:a )?target))[.!]?\s*",
        answer.lower().replace("’", "'"),
    ))
    answered = {f for f in pending if (declined and f not in REQUIRED) or draft.get(f) not in (None, 0, [])}
    draft["answered"] = sorted(set(draft.get("answered", [])) | answered)
    draft = _apply_household(session, draft, agent.db)
    req.clarifications = list(req.clarifications) + [{"questions": req.pending_questions, "answer": answer}]
    req.draft_payload = draft
    still_open = [q for q in req.pending_questions if q["field"] not in answered and q["field"] not in REQUIRED]
    new_ambiguities = [a for a in result.data.get("ambiguities", []) if a["field"] not in pending]
    req.pending_questions = _questions(draft, still_open + new_ambiguities)
    _stage_after_update(req)
    agent.log("clarify_constraints", f"Updated: {_summary(draft)}", session_id=session.id, llm=result,
              confidence=0.6 if req.pending_questions else 0.9)
    return req


def correct(agent, req: ShoppingRequest, *, text: str | None = None, patch: dict | None = None) -> ShoppingRequest:
    """4a — a correction. The third one moves the request into structured-form mode."""
    _ensure_draft(req)
    if req.mode == InputMode.form:
        raise IntakeError("Please edit your details directly in the form, then save and confirm them.")
    if not (text and text.strip()) and not patch:
        raise IntakeError("Tell me what to change before submitting a correction.")
    session = req.session
    req.correction_count += 1
    draft = dict(req.draft_payload)
    result = None
    if text:
        result = agent.think("extract_constraints", {"text": text, "draft": draft, "household": _household_context(session, agent.db)})
        draft = _merge(draft, result.data)
    if patch:
        draft = _apply_patch(draft, patch)
    draft = _apply_household(session, draft, agent.db)
    req.draft_payload = draft
    # An unrelated correction must not silently drop questions the shopper hasn't answered yet.
    new_ambiguities = result.data.get("ambiguities", []) if result else []
    req.pending_questions = _questions(draft, _still_open(req.pending_questions, draft) + new_ambiguities)
    if req.mode == InputMode.text and req.correction_count >= get_settings().max_corrections:
        req.mode = InputMode.form
    _stage_after_update(req)
    agent.log(
        "correct_constraints",
        f"Correction {req.correction_count}: {_summary(draft)}" + ("; switched to structured form" if req.mode == InputMode.form else ""),
        session_id=session.id, llm=result,
    )
    return req


def submit_form(agent, req: ShoppingRequest, form: dict) -> ShoppingRequest:
    _ensure_draft(req)
    req.mode = InputMode.form
    draft = _apply_household(req.session, _apply_patch(dict(req.draft_payload), form), agent.db)
    req.draft_payload = draft
    req.pending_questions = _questions(draft, _still_open(req.pending_questions, draft))
    _stage_after_update(req)
    if not req.pending_questions:
        req.stage = IntakeStage.awaiting_confirmation
    agent.log("submit_form", f"Form submitted: {_summary(draft)}", session_id=req.session_id)
    return req


def confirm(agent, req: ShoppingRequest) -> ConstraintSetRecord:
    """Step 5 — save the version, activate it and confirm the request as one commit."""
    _ensure_draft(req)
    missing = [f for f in REQUIRED if req.draft_payload.get(f) in (None, 0)]
    if missing:
        raise IntakeError("Still need: " + ", ".join(missing))
    if req.pending_questions:
        raise IntakeError("Please answer the remaining clarification questions before confirming.")
    if req.stage == IntakeStage.awaiting_form:
        raise IntakeError("Please submit the structured form before confirming.")
    _validate_values(req.draft_payload)
    db = agent.db
    session = req.session
    # All three changes ride on the request's single DB transaction (committed by the
    # API layer), so either the version, the active link and the request status are
    # all saved, or none are.
    try:
        version = (db.scalar(select(func.max(ConstraintSetRecord.version)).where(ConstraintSetRecord.session_id == session.id)) or 0) + 1
        payload = {k: v for k, v in req.draft_payload.items() if k not in ("answered", "preferences_override")}
        cs = ConstraintSetRecord(session_id=session.id, request_id=req.id, version=version, confirmed_at=datetime.now(), payload=payload)
        db.add(cs)
        db.flush()
        session.activate(cs)
        if payload.get("goal_hint"):
            session.goal = payload["goal_hint"]
        req.confirm()
    except Exception as exc:  # 5a: report, keep the previous active set
        db.rollback()
        raise IntakeError("Saving failed. Your previous constraints are unchanged. Try again.") from exc
    agent.log("confirm_constraints", f"Constraint set v{cs.version} active: {_summary(cs.payload)}", session_id=session.id, confidence=1.0)
    return cs


def cancel(agent, req: ShoppingRequest) -> ShoppingRequest:
    if req.status == RequestStatus.draft:
        req.status, req.stage = RequestStatus.cancelled, IntakeStage.ended
        agent.log("cancel_request", "Request cancelled; previous constraints preserved", session_id=req.session_id)
    return req


def state(req: ShoppingRequest) -> dict:
    draft = req.draft_payload or {}
    return {
        "request_id": req.id,
        "raw_text": req.raw_text,
        "status": req.status,
        "stage": req.stage,
        "mode": req.mode,
        "correction_count": req.correction_count,
        "max_corrections": get_settings().max_corrections,
        "draft": draft,
        "questions": req.pending_questions,
        "missing_fields": [f for f in REQUIRED if draft.get(f) in (None, 0)],
        "assumptions": draft.get("assumptions", []),
    }


def _ensure_draft(req: ShoppingRequest) -> None:
    if req.status != RequestStatus.draft:
        raise IntakeError(f"This request is already {req.status}.")


def _validate_numbers(values: dict) -> None:
    limits = {"budget": (None, False), "household_size": (20, True), "meals_per_day": (5, False), "days": (31, True)}
    for key, (maximum, whole) in limits.items():
        value = values.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise IntakeError(f"{key.replace('_', ' ').capitalize()} must be a positive number.")
        if whole and value != int(value):
            raise IntakeError(f"{key.replace('_', ' ').capitalize()} must be a whole number.")
        if maximum is not None and value > maximum:
            raise IntakeError(f"{key.replace('_', ' ').capitalize()} must be at most {maximum}.")


def _apply_patch(draft: dict, patch: dict) -> dict:
    _validate_values(patch)
    out = dict(draft)
    for key in REQUIRED:
        if key in patch and patch[key] is not None:
            out[key] = patch[key]
    if "restrictions" in patch and patch["restrictions"] is not None:
        out["restrictions"] = [
            {"restriction": normalise_restriction(r["restriction"]), "severity": r.get("severity", "severe"),
             "source": "request", "label": label(r["restriction"])}
            for r in patch["restrictions"]
        ]  # household-locked ones are re-added by _apply_household
    if "nutritional_targets" in patch and patch["nutritional_targets"] is not None:
        out["nutritional_targets"] = patch["nutritional_targets"]
        out["answered"] = sorted(set(out.get("answered", [])) | {"nutritional_targets"})
    if "preferences" in patch and patch["preferences"] is not None:
        out["preferences"] = sorted(set(p.strip() for p in patch["preferences"]))
        out["preferences_override"] = True
    if "goal_hint" in patch:
        out["goal_hint"] = patch["goal_hint"]
    return out


def _validate_values(values: dict) -> None:
    """Validate both typed forms and free-form correction patches before persistence."""
    _validate_numbers(values)
    for key in ("restrictions", "nutritional_targets", "preferences"):
        if values.get(key) is not None and not isinstance(values[key], list):
            raise IntakeError(f"{key.replace('_', ' ').capitalize()} must be a list.")
    for r in values.get("restrictions") or []:
        if not isinstance(r, dict) or not isinstance(r.get("restriction"), str):
            raise IntakeError("Each restriction needs a supported restriction name.")
        if normalise_restriction(r["restriction"]) not in RESTRICTION_RULES:
            raise IntakeError(f"Unsupported restriction: {r['restriction']}.")
        if not isinstance(r.get("severity", "severe"), str) or r.get("severity", "severe") not in set(Severity):
            raise IntakeError("Choose a valid restriction severity.")
    for t in values.get("nutritional_targets") or []:
        if not isinstance(t, dict) or not isinstance(t.get("nutrient"), str) or not t["nutrient"].strip():
            raise IntakeError("Each nutrition target needs a nutrient name.")
        value = t.get("minimum_per_day")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise IntakeError("Nutrition targets must be positive numbers per person per day.")
    for preference in values.get("preferences") or []:
        if not isinstance(preference, str) or not re.fullmatch(r"(?:like|dislike|brand|avoid_brand):\s*\S.*", preference.strip()):
            raise IntakeError("Preferences must use like:, dislike:, brand:, or avoid_brand: followed by a food or brand.")
    if values.get("goal_hint") is not None and (not isinstance(values["goal_hint"], str) or values["goal_hint"] not in set(OptimisationGoal)):
        raise IntakeError("Choose a supported optimisation goal.")
