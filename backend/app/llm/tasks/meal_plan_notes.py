"""UC-08 — a short cook's note on top of the deterministic meal plan. Owner: Intake & Optimisation."""

from __future__ import annotations

import json

from app.llm.tasks._base import Task

SYSTEM = """You are the AI Personal Shopper of Trolley Mate. Given a computed meal
plan, write 2-3 sentences of practical cooking advice: what to cook first (most
perishable), and which ingredients are reused across meals. Only mention meals and
ingredients that appear in the plan. No markdown."""


def build_user(ctx: dict) -> str:
    return json.dumps(ctx, indent=1)


def mock(ctx: dict) -> str:
    parts = [f"This plan covers {ctx['planned']} of {ctx['requested']} meals."]
    if ctx.get("reused"):
        parts.append("Packs are shared across meals: " + ", ".join(ctx["reused"][:4]) + ".")
    if ctx.get("perishable_first"):
        parts.append(f"Cook with {', '.join(ctx['perishable_first'][:3])} early in the week while it's fresh.")
    if ctx.get("missing"):
        parts.append(f"{ctx['missing']} meal(s) need a few extra items — see the suggestions below.")
    return " ".join(parts)


TASK = Task(name="meal_plan_notes", system=SYSTEM, build_user=build_user, mock=mock)
