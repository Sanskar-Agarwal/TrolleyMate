"""Turn "Jamie is now vegetarian" or "add Kit, a child with a peanut allergy" into profile changes (1.2.13).

Chat can only add: a restriction for a member, or a new member. Taking an allergy away stays on the
Household page, where the shopper sees exactly what they're removing.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel

from app.llm.tasks._base import Task, nullable, obj
from app.services.dietary_rules import RESTRICTION_RULES, normalise_restriction

SYSTEM = f"""You update a household's dietary profile for Trolley Mate, a grocery shopper.
From the shopper's message, list the changes as operations:
- add_restriction: an existing member now has a restriction (member, restriction, severity)
- add_member: a new person joins the household (member, age_group, optional restriction)
- remove: the shopper wants to remove a member or restriction (member, restriction)
Restriction ids must be one of: {", ".join(RESTRICTION_RULES)}.
severity is severe for allergies unless the shopper says mild; moderate for intolerances.
age_group is adult, teen, child or senior. If the message is unclear, ask in clarification_question."""

SCHEMA = obj({
    "operations": {"type": "array", "items": obj({
        "op": {"type": "string", "enum": ["add_restriction", "add_member", "remove"]},
        "member": {"type": "string"},
        "restriction": nullable("string"),
        "severity": nullable("string", enum=["severe", "moderate", "mild", None]),
        "age_group": nullable("string", enum=["adult", "teen", "child", "senior", None]),
    })},
    "clarification_question": nullable("string"),
})


class Operation(BaseModel):
    op: str
    member: str
    restriction: str | None = None
    severity: str | None = None
    age_group: str | None = None


class Output(BaseModel):
    operations: list[Operation] = []
    clarification_question: str | None = None


def build_user(ctx: dict) -> str:
    return f"Household members: {json.dumps(ctx['members'])}\nShopper message: {ctx['text']}"


_PHRASES = {
    "vegetarian": "vegetarian", "vegan": "vegan", "halal": "halal", "coeliac": "gluten", "celiac": "gluten",
    "lactose intolerant": "lactose", "gluten free": "gluten", "gluten-free": "gluten",
}


def _restriction(text: str) -> str | None:
    for phrase, rid in _PHRASES.items():
        if phrase in text:
            return rid
    m = re.search(r"allerg(?:y|ic) to ([a-z ]+?)(?:\.|,|$| and )|([a-z ]+?) allergy", text)
    if m:
        rid = normalise_restriction((m.group(1) or m.group(2)).strip().split(" ")[-1])
        return rid if rid in RESTRICTION_RULES else None
    return None


def mock(ctx: dict) -> dict:
    text = ctx["text"].lower().strip()
    names = {m.lower(): m for m in ctx["members"]}
    restriction = _restriction(text)
    severity = "mild" if "mild" in text else ("moderate" if restriction and RESTRICTION_RULES[restriction]["kind"] == "intolerance" else "severe")
    ops: list[dict] = []
    if re.search(r"\b(remove|no longer|isn't .* any ?more|not .* anymore|delete)\b", text):
        who = next((n for k, n in names.items() if k in text), "")
        ops.append({"op": "remove", "member": who, "restriction": restriction, "severity": None, "age_group": None})
    elif m := re.search(r"\badd (?:a |an )?(?:new )?(?:member )?([a-z]+)", text):
        age = next((a for a in ("child", "teen", "senior", "adult") if a in text), "adult")
        name = m.group(1).title()
        if name.lower() in ("child", "teen", "senior", "adult", "kid"):
            name = "New member"
        ops.append({"op": "add_member", "member": name, "restriction": restriction, "severity": severity if restriction else None, "age_group": age})
    else:
        who = next((n for k, n in names.items() if re.search(rf"\b{re.escape(k)}\b", text)), None)
        if who and restriction:
            ops.append({"op": "add_restriction", "member": who, "restriction": restriction, "severity": severity, "age_group": None})
    question = None if ops else "Who is this for, and what should they avoid? For example: \"Jamie is now vegetarian.\""
    return {"operations": ops, "clarification_question": question}


TASK = Task(name="household_edit", system=SYSTEM, build_user=build_user, mock=mock, schema=SCHEMA, output_model=Output)
