"""UC-09 — interpret a conversational basket edit against the current basket. Owner: Pricing & Editing."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from app.llm.tasks._base import Task, nullable, obj

SYSTEM = """You interpret basket edits for Trolley Mate, an AI grocery shopper.
You get the current basket (item names) and the shopper's request. Return a list of
operations. `target` must quote words from an existing basket item name when the
operation acts on an existing item. `replacement` is a short product description
(e.g. "chicken", "brown rice") for replace/add.
Operations: replace, remove, add, increase, decrease.
budget_change: {"mode": "delta", "amount": -10} for "make it $10 cheaper",
{"mode": "absolute", "amount": 80} for "keep it under $80", or null.
If the request is genuinely ambiguous (you cannot tell which item is meant),
set clarification_question and return no operations. Never relax allergies or diets."""

SCHEMA = obj(
    {
        "operations": {
            "type": "array",
            "items": obj(
                {
                    "op": {"type": "string", "enum": ["replace", "remove", "add", "increase", "decrease"]},
                    "target": nullable("string"),
                    "replacement": nullable("string"),
                }
            ),
        },
        "budget_change": {
            "anyOf": [
                {"type": "null"},
                obj({"mode": {"type": "string", "enum": ["delta", "absolute"]}, "amount": {"type": "number"}}),
            ]
        },
        "clarification_question": nullable("string"),
        "summary": {"type": "string"},
    }
)


class _Op(BaseModel):
    op: str
    target: str | None = None
    replacement: str | None = None


class _Budget(BaseModel):
    mode: str
    amount: float


class Output(BaseModel):
    operations: list[_Op] = Field(default_factory=list)
    budget_change: _Budget | None = None
    clarification_question: str | None = None
    summary: str = ""


def build_user(ctx: dict) -> str:
    return f"Current basket items: {json.dumps(ctx['items'])}\nShopper request: {ctx['text']}"


def mock(ctx: dict) -> dict:
    text = ctx["text"].lower()
    ops: list[dict] = []
    for m in re.finditer(r"(?:replace|swap) (?:the )?([a-z ]+?) (?:with|for) ([a-z ]+?)(?=$| and|,|\.)", text):
        ops.append({"op": "replace", "target": m.group(1).strip(), "replacement": m.group(2).strip()})
    for m in re.finditer(r"(?:remove|drop|no more|get rid of) (?:the )?([a-z ]+?)(?=$| and|,|\.)", text):
        ops.append({"op": "remove", "target": m.group(1).strip(), "replacement": None})
    for m in re.finditer(r"\badd (?:some |a |an )?([a-z ]+?)(?=$| and|,|\.)", text):
        ops.append({"op": "add", "target": None, "replacement": m.group(1).strip()})
    for m in re.finditer(r"\bmore ([a-z ]+?)(?=$| and|,|\.)", text):
        ops.append({"op": "increase", "target": m.group(1).strip(), "replacement": None})
    for m in re.finditer(r"\b(?:less|fewer) ([a-z ]+?)(?=$| and|,|\.)", text):
        ops.append({"op": "decrease", "target": m.group(1).strip(), "replacement": None})

    budget = None
    if m := re.search(r"\$\s?(\d+(?:\.\d+)?) cheaper", text):
        budget = {"mode": "delta", "amount": -float(m.group(1))}
    elif m := re.search(r"(?:under|below|at most|max(?:imum)?|make it|budget (?:of|to)|change (?:it|the budget) to) \$\s?(\d+(?:\.\d+)?)", text):
        budget = {"mode": "absolute", "amount": float(m.group(1))}
    elif m := re.search(r"\$\s?(\d+(?:\.\d+)?) more", text):
        budget = {"mode": "delta", "amount": float(m.group(1))}
    elif re.search(r"\bcheaper\b", text) and not ops:
        budget = {"mode": "delta", "amount": -5.0}

    question = None
    if not ops and budget is None:
        question = "Which item would you like me to change, and how?"
    parts = [f"{o['op']} {o.get('target') or ''}{' → ' + o['replacement'] if o.get('replacement') else ''}".strip() for o in ops]
    if budget:
        parts.append(f"budget {budget['mode']} {budget['amount']:+g}" if budget["mode"] == "delta" else f"budget ≤ ${budget['amount']:g}")
    return {"operations": ops, "budget_change": budget, "clarification_question": question, "summary": "; ".join(parts)}


TASK = Task(name="parse_edit", system=SYSTEM, build_user=build_user, mock=mock, schema=SCHEMA, output_model=Output)
