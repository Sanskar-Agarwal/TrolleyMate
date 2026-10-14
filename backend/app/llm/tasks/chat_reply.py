"""General chat replies (greetings, help) from the supervisor. Owner: Platform."""

from __future__ import annotations

import json

from app.llm.tasks._base import Task

SYSTEM = """You are Trolley Mate, an AI grocery personal shopper for Australian households.
Reply briefly (1-2 sentences). If the shopper seems unsure what to do, suggest they
describe their budget, how many meals, for how many days, and any allergies.
Never give medical advice; for allergy questions, say a dietitian can review uncertain items."""


def build_user(ctx: dict) -> str:
    return f"Conversation state: {json.dumps(ctx.get('state', {}))}\nShopper: {ctx['text']}"


def mock(ctx: dict) -> str:
    if ctx.get("state", {}).get("has_basket"):
        return "Your basket is ready. You can ask me to swap items, make it cheaper, explain a choice, or plan meals from it."
    return (
        "Tell me what you need — for example: \"$90 for the week, dinners for two, "
        "one of us has a nut allergy\" — and I'll build a basket that fits."
    )


TASK = Task(name="chat_reply", system=SYSTEM, build_user=build_user, mock=mock)
