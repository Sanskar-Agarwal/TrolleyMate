"""UC-04 — state a substitution's trade-off plainly. Owner: Negotiation & Substitution."""

from __future__ import annotations

import json

from app.llm.tasks._base import Task

SYSTEM = """You are the AI Personal Shopper of Trolley Mate. Write ONE sentence that
states the trade-off of swapping one grocery product for another, e.g.
"Home-brand pasta of the same weight saves $1.00 but has slightly less fibre."
Use only the facts given. Always mention the price difference. Mention any
warning in the facts (allergens, nutrition drops). No markdown."""


def build_user(ctx: dict) -> str:
    return json.dumps(ctx, indent=1)


def mock(ctx: dict) -> str:
    saving = ctx["saving"]
    money = f"saves ${saving:.2f}" if saving > 0.004 else (f"costs ${-saving:.2f} more" if saving < -0.004 else "costs the same")
    sentence = f"{ctx['replacement']} instead of {ctx['original']} {money}"
    notes = [w for w in ctx.get("notes", []) if w]
    if notes:
        sentence += ", but " + "; ".join(notes)
    return sentence + "."


TASK = Task(name="tradeoff", system=SYSTEM, build_user=build_user, mock=mock)
