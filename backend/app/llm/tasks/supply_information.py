"""UC-06 ext step 5a — the compliance agent answers a dietitian's information request. Owner: Governance."""

from __future__ import annotations

import json

from app.llm.tasks._base import Task

SYSTEM = """You are the AI Nutrition & Compliance agent of Trolley Mate answering a
registered dietitian who is reviewing an escalated product. Answer their question
using ONLY the product record provided. If the record does not contain the answer,
say exactly what is missing. Do not state that the product is safe. 2-4 sentences."""


def build_user(ctx: dict) -> str:
    return f"Dietitian question: {ctx['question']}\nProduct record:\n{json.dumps(ctx['product'], indent=1)}"


def mock(ctx: dict) -> str:
    p = ctx["product"]
    ingredients = ", ".join(p.get("ingredients") or []) or "no ingredient list on file"
    parts = [f"Record for {p['name']} ({p.get('brand') or 'unbranded'}): ingredients — {ingredients}."]
    if p.get("may_contain"):
        parts.append("Label warning: may contain " + ", ".join(p["may_contain"]) + ".")
    if not p.get("data_complete", True):
        parts.append("The retailer feed did not include a complete ingredient list, so allergen status cannot be confirmed from our data.")
    return " ".join(parts)


TASK = Task(name="supply_information", system=SYSTEM, build_user=build_user, mock=mock)
