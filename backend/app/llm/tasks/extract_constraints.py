"""UC-01 — turn a natural-language grocery request into proposed constraints. Owner: Intake."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from app.llm.tasks._base import Task, nullable, obj
from app.services.dietary_rules import RESTRICTION_RULES, normalise_restriction

SYSTEM = f"""You are the intake step of Trolley Mate, an AI grocery personal shopper.
Read the shopper's message and extract shopping constraints. Never invent a value
the shopper did not state or clearly imply; leave it null and add an ambiguity
with a short, friendly question instead.

Rules:
- budget is in AUD for the whole shop.
- days: "this week" = 7, "fortnight" = 14, "weekend" = 2.
- meals_per_day counts the meals the shop must cover per person (e.g. "lunch and dinner" = 2).
- household_size: "for myself" = 1, "me and my partner" = 2. Leave null if not said.
- restrictions use ONLY these ids: {", ".join(sorted(RESTRICTION_RULES))}.
  Allergies are severity "severe"; intolerances "moderate"; diets (vegetarian, vegan, halal) "moderate".
  "Nut allergy" means both tree_nuts and peanuts.
- Vague nutrition goals like "high protein" are ambiguous: ask for a number.
- preferences are soft dislikes/likes written as "dislike:<food>" or "like:<food>" or "brand:<name>".
- goal_hint is one of lowest_cost, best_nutrition, least_waste, fastest_cook, balanced, or null.
- interpretation_ok is false only if the message is not a grocery request at all.
If a current draft is given, only return fields the new message changes; return null for the rest.
"""

SCHEMA = obj(
    {
        "budget": nullable("number"),
        "household_size": nullable("integer"),
        "meals_per_day": nullable("number"),
        "days": nullable("integer"),
        "restrictions": {
            "type": "array",
            "items": obj({"restriction": {"type": "string"}, "severity": {"type": "string"}}),
        },
        "nutritional_targets": {
            "type": "array",
            "items": obj({"nutrient": {"type": "string"}, "minimum_per_day": {"type": "number"}}),
        },
        "preferences": {"type": "array", "items": {"type": "string"}},
        "ambiguities": {
            "type": "array",
            "items": obj({"field": {"type": "string"}, "question": {"type": "string"}}),
        },
        "goal_hint": nullable("string"),
        "interpretation_ok": {"type": "boolean"},
    }
)


class _Restriction(BaseModel):
    restriction: str
    severity: str = "severe"


class _Target(BaseModel):
    nutrient: str
    minimum_per_day: float


class _Ambiguity(BaseModel):
    field: str
    question: str


class Output(BaseModel):
    budget: float | None = None
    household_size: int | None = None
    meals_per_day: float | None = None
    days: int | None = None
    restrictions: list[_Restriction] = Field(default_factory=list)
    nutritional_targets: list[_Target] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    ambiguities: list[_Ambiguity] = Field(default_factory=list)
    goal_hint: str | None = None
    interpretation_ok: bool = True


def build_user(ctx: dict) -> str:
    parts = [f"Shopper message: {ctx['text']}"]
    if ctx.get("draft"):
        parts.append(f"Current draft constraints: {json.dumps(ctx['draft'])}")
    if ctx.get("pending_fields"):
        parts.append(f"The shopper is answering questions about: {', '.join(ctx['pending_fields'])}")
    if ctx.get("household"):
        parts.append(f"Saved household profile: {json.dumps(ctx['household'])}")
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Offline mock: a rule-based extractor that covers the demo script and tests.
# --------------------------------------------------------------------------

_WORDS = {
    "a": 1, "an": 1, "one": 1, "single": 1, "two": 2, "couple": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fourteen": 14,
}
_NUM = r"(\d+(?:\.\d+)?|" + "|".join(_WORDS) + r")"
_MEALS = ("breakfast", "lunch", "dinner")
_ALLERGEN_WORDS = {
    "nut": ["tree_nuts", "peanuts"], "nuts": ["tree_nuts", "peanuts"], "tree nut": ["tree_nuts"],
    "tree nuts": ["tree_nuts"], "peanut": ["peanuts"], "peanuts": ["peanuts"], "dairy": ["milk"],
    "milk": ["milk"], "egg": ["egg"], "eggs": ["egg"], "shellfish": ["shellfish"], "prawns": ["shellfish"],
    "prawn": ["shellfish"], "fish": ["fish"], "soy": ["soy"], "gluten": ["gluten"], "wheat": ["wheat"],
    "sesame": ["sesame"], "pork": ["pork_free"],
}


def _n(token: str) -> float | None:
    try:
        return float(token)
    except ValueError:
        return _WORDS.get(token)


def mock(ctx: dict) -> dict:
    text = " " + ctx["text"].lower().replace("’", "'") + " "
    pending = ctx.get("pending_fields") or []
    out: dict = {
        "budget": None, "household_size": None, "meals_per_day": None, "days": None,
        "restrictions": [], "nutritional_targets": [], "preferences": [], "ambiguities": [],
        "goal_hint": None, "interpretation_ok": True,
    }

    # Budget
    m = (
        re.search(r"\$\s?(\d+(?:\.\d{1,2})?)", text)
        or re.search(r"(\d+(?:\.\d{1,2})?)\s*(?:dollars|bucks|aud)\b", text)
        or re.search(r"budget (?:of |is |around )?(\d+(?:\.\d{1,2})?)", text)
    )
    if m:
        out["budget"] = float(m.group(1))

    # Days
    if re.search(r"fortnight|two weeks|2 weeks", text):
        out["days"] = 14
    elif m := re.search(r"(?<!meals )(?<!meal )\b(\d+|two|three|four|five|six|seven|eight|nine|ten|fourteen) days?\b", text):
        out["days"] = int(_n(m.group(1)) or 0) or None
    elif re.search(r"\bweek\b|weekly", text):
        out["days"] = 7
    elif "weekend" in text:
        out["days"] = 2
    elif re.search(r"\btoday\b|\btonight\b", text):
        out["days"] = 1

    # Meals per day
    if m := re.search(_NUM + r" meals? (?:a|per|each|every) day", text):
        out["meals_per_day"] = _n(m.group(1))
    else:
        named = [meal for meal in _MEALS if meal in text]
        if named:
            out["meals_per_day"] = float(len(named))
        elif "dinners" in text:
            out["meals_per_day"] = 1.0

    # Household size
    if re.search(r"for myself|just me|only me|i live alone|for me\b|by myself", text):
        out["household_size"] = 1
    elif m := re.search(r"(?:family of|for|feed) " + _NUM + r"(?: people| persons| of us| adults)?\b(?! days?| weeks?| meals?| dollars)", text):
        size = _n(m.group(1))
        if size and size < 15 and not re.search(r"\$\s?" + re.escape(m.group(1)), text):
            out["household_size"] = int(size)
    if re.search(r"me and my (partner|wife|husband|flatmate|girlfriend|boyfriend)|the two of us|us two|both of us|my partner and i", text):
        out["household_size"] = 2

    # Restrictions
    found: dict[str, str] = {}
    if re.search(r"lactose[- ]intolerant|lactose intolerance|no lactose", text):
        found["lactose"] = "moderate"
    if re.search(r"gluten[- ]free|coeliac|celiac", text):
        found["gluten"] = "severe"
    if re.search(r"dairy[- ]free", text):
        found["milk"] = "severe"
    for diet in ("vegetarian", "vegan", "halal"):
        if diet in text:
            found[diet] = "moderate"
    for m in re.finditer(r"allerg(?:ic|y|ies) to ([a-z ,]+?)(?:[.;]| and i| but|$)", text):
        for word in re.split(r",| and | or ", m.group(1)):
            for r in _ALLERGEN_WORDS.get(word.strip(), []):
                found[r] = "severe"
    for m in re.finditer(r"([a-z]+(?: nut)?) allerg(?:y|ies)", text):
        for r in _ALLERGEN_WORDS.get(m.group(1).strip(), []):
            found[r] = "severe"
    for m in re.finditer(r"\b(?:no|without|avoid) (tree nuts?|nuts?|peanuts?|dairy|eggs?|shellfish|prawns?|fish|gluten|wheat|soy|sesame|pork)\b", text):
        for r in _ALLERGEN_WORDS.get(m.group(1), []):
            found.setdefault(r, "severe")
    out["restrictions"] = [{"restriction": normalise_restriction(k), "severity": v} for k, v in found.items()]

    # Nutrition
    if m := re.search(r"(\d+)\s*g(?:rams)?\s*(?:of\s*)?protein", text):
        out["nutritional_targets"].append({"nutrient": "protein_g", "minimum_per_day": float(m.group(1))})
    elif re.search(r"high[- ]protein|more protein|lots of protein", text):
        out["ambiguities"].append({
            "field": "nutritional_targets",
            "question": "How much protein per person per day are you aiming for? (for example 120 g)",
        })

    # Preferences (soft) — "no X" / "don't like X" where X is not an allergen
    for m in re.finditer(r"(?:don't|do not|dont) (?:like|eat|want) ([a-z]+)|\bhate ([a-z]+)|\bno ([a-z]+)", text):
        word = next(g for g in m.groups() if g)
        if word not in _ALLERGEN_WORDS and word not in ("lactose", "more", "longer", "budget", "meat", "tree", "need"):
            out["preferences"].append(f"dislike:{word.rstrip('s') if word.endswith('ms') else word}")
    if re.search(r"\bno meat\b", text) and "vegetarian" not in found:
        out["restrictions"].append({"restriction": "vegetarian", "severity": "moderate"})

    # Goal hint
    if re.search(r"cheap|save money|tight budget|as little as", text):
        out["goal_hint"] = "lowest_cost"
    elif re.search(r"healthy|nutritious|nutrition", text):
        out["goal_hint"] = "best_nutrition"
    elif re.search(r"quick|fast|easy to cook|no time", text):
        out["goal_hint"] = "fastest_cook"
    elif re.search(r"waste", text):
        out["goal_hint"] = "least_waste"

    # Answers to clarifying questions are often bare values ("80", "dinner only").
    if pending:
        bare = re.fullmatch(r"\s*\$?\s*(\d+(?:\.\d+)?)\s*(?:g|grams?|dollars|days|people|a day|per day)?\.?\s*", text)
        if bare:
            value = float(bare.group(1))
            for field in ("budget", "days", "meals_per_day", "household_size", "nutritional_targets"):
                if field in pending and out.get(field) in (None, []):
                    if field == "nutritional_targets":
                        out[field] = [{"nutrient": "protein_g", "minimum_per_day": value}]
                    elif field in ("days", "household_size"):
                        out[field] = int(value)
                    else:
                        out[field] = value
                    break
        if "meals_per_day" in pending and out["meals_per_day"] is None and "only" in text:
            out["meals_per_day"] = float(max(1, sum(meal in text for meal in _MEALS)))

    extracted_anything = any(
        out[k] not in (None, []) for k in ("budget", "household_size", "meals_per_day", "days", "restrictions", "nutritional_targets", "preferences")
    )
    if not extracted_anything and not pending and not re.search(r"food|grocer|shop|meal|cook|eat|basket", text):
        out["interpretation_ok"] = False
    return out


TASK = Task(name="extract_constraints", system=SYSTEM, build_user=build_user, mock=mock, schema=SCHEMA, output_model=Output)
