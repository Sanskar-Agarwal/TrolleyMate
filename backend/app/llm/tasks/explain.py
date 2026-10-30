"""UC-07 — plain-language explanations grounded ONLY in recorded facts. Owner: Governance."""

from __future__ import annotations

import json

from app.llm.tasks._base import Task

SYSTEM = """You are the AI Technical Manager of Trolley Mate. Explain a grocery
recommendation to the shopper in plain, friendly language (3-5 short sentences).
Use ONLY the facts provided. Do not add reasons, prices or claims that are not in
the facts. If a fact needed for an explanation is missing, or `evidence_missing`
lists anything, say plainly that part of the reasoning is unavailable — never guess
it. scheduled_meals counts meals for the whole household; person_meals is only
an adult-equivalent portion count for sizing, not the number of scheduled meals. When a safety `verdict` is given, mention its outcome. No markdown headings."""


def build_user(ctx: dict) -> str:
    return f"Scope: {ctx.get('scope', 'basket')}\nRecorded facts:\n{json.dumps(ctx['facts'], indent=1)}"


def mock(ctx: dict) -> str:
    f = ctx["facts"]
    if ctx.get("scope") == "item":
        parts = [f"{f['item']} was chosen as a {f.get('role', 'basket')} item."]
        if f.get("reason"):
            parts.append(f["reason"].rstrip(".") + ".")
        if f.get("compliance"):
            parts.append(f"Dietary check: {f['compliance']}.")
        if f.get("alternatives"):
            parts.append("Cheaper or similar options considered: " + ", ".join(f["alternatives"][:3]) + ".")
        parts.extend(_missing(f))
        return " ".join(parts)

    goal = (f.get("strategy") or f.get("goal", "balanced").replace("_", " ")).lower()
    parts = [f"I optimised this basket for {goal} within your ${f.get('budget', 0):.2f} budget (total ${f.get('total', 0):.2f})."]
    if f.get("restrictions"):
        parts.append("Every item was checked against: " + ", ".join(f["restrictions"]) + "; these are never traded away.")
    n = f.get("nutrition") or {}
    if n:
        parts.append(
            f"It provides about {n.get('protein_g', 0):.0f} g of protein "
            f"and {n.get('veg_serves', 0):.0f} vegetable serves."
        )
    if f.get("excluded"):
        parts.append(f"{len(f['excluded'])} products were excluded for dietary reasons, e.g. {f['excluded'][0]}.")
    if f.get("withheld"):
        parts.append(f"{', '.join(f['withheld'])} is held back until a dietitian confirms it is safe.")
    verdict = f.get("verdict")
    if verdict:
        parts.append(f"The latest safety check was {verdict['status']} ({round(verdict['confidence'] * 100)}% confidence).")
    if f.get("nutrition_adequate") is False:
        parts.append("Nutrition targets are not yet met. Repair the gaps or explicitly accept an allowed nutrition exception before accepting the basket; mandatory dietary restrictions still apply.")
    parts.extend(_missing(f))
    return " ".join(parts)


_MISSING_LABELS = {
    "constraints": "the confirmed constraints", "prices": "the price quotes", "price": "the price quote",
    "verdict": "the safety verdict", "compliance": "the safety check", "tools": "the optimiser results",
    "audit_trail": "the agent decision log",
}


def _missing(f: dict) -> list[str]:
    missing = [_MISSING_LABELS.get(k, k) for k in f.get("evidence_missing") or []]
    if not missing:
        return []
    return [f"No record of {', '.join(missing)} is available, so that part of the reasoning can't be shown."]


TASK = Task(name="explain", system=SYSTEM, build_user=build_user, mock=mock)
