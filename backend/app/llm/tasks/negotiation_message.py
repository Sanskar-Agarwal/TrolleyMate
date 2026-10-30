"""UC-03 — explain an infeasible request and the trade-offs on offer. Owner: Negotiation & Substitution."""

from __future__ import annotations

import json

from app.llm.tasks._base import Task

SYSTEM = """You are the AI Personal Shopper of Trolley Mate. The shopper's constraints
cannot all be met. In 2-3 friendly sentences, say what cannot be met and present the
options exactly as given (do not invent new numbers). If timed_out is true and there are
no options, say the search couldn't finish and suggest trying again. Make clear that
allergies and dietary restrictions will not be relaxed. No markdown."""


def build_user(ctx: dict) -> str:
    return json.dumps(ctx, indent=1)


def mock(ctx: dict) -> str:
    parts = [f"I can't fit {ctx['requested_meals']} person-meals into ${ctx['budget']:.2f} while keeping every dietary rule."]
    if ctx.get("blocked_roles"):
        parts = [f"Your dietary rules leave no suitable {', '.join(ctx['blocked_roles'])} options in the catalogue, so I can't build a complete basket."]
    options = []
    if ctx.get("extra_needed") is not None:
        options.append(f"raise the budget by ${ctx['extra_needed']:.2f} to ${ctx['min_budget']:.2f}")
    if ctx.get("max_meals"):
        options.append(f"keep ${ctx['budget']:.2f} and cover {ctx['max_meals']} person-meals instead")
    if options:
        parts.append("You could " + " or ".join(options) + ".")
    elif ctx.get("timed_out"):
        parts.append("I couldn't finish working out the alternatives, so please try again.")
    parts.append("Your allergies and dietary restrictions stay in place either way.")
    return " ".join(parts)


TASK = Task(name="negotiation_message", system=SYSTEM, build_user=build_user, mock=mock)
