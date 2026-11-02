"""Supervisor routing — decide what a chat message is asking for. Owner: Platform/Intake."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel

from app.llm.tasks._base import Task, obj

INTENTS = ["new_request", "clarify_answer", "correct_request", "cancel_request", "edit_basket", "explain", "meal_plan", "compare_prices",
           "price_question", "edit_household", "chat"]

SYSTEM = f"""You route messages for Trolley Mate, an AI grocery personal shopper.
Classify the shopper's latest message into exactly one intent:
- new_request: describes a new shop (budget, meals, people, diet) or asks to start over
- clarify_answer: answers a question the shopper was just asked
- correct_request: changes the current unconfirmed draft; keep the same request even if a basket already exists
- cancel_request: cancels the current unconfirmed draft
- edit_basket: asks to change the current basket (swap, remove, add, cheaper, more of)
- explain: asks why something was chosen or how the basket was built
- meal_plan: asks for meals/recipes from the basket
- compare_prices: asks which store is cheapest overall, or about savings
- price_question: asks about one product's price, e.g. "why is the chicken cheaper at ValueMart?"
- edit_household: changes who's in the household or their diets/allergies, e.g. "Jamie is now vegetarian"
- chat: anything else (greetings, thanks, help)
If draft_stage is present, keep changes in that draft; use new_request only for an explicit fresh shop or start-over.
Use the conversation state to decide. Intents: {", ".join(INTENTS)}.
Also write a one-sentence `reply` the assistant could show while it works."""

SCHEMA = obj(
    {
        "intent": {"type": "string", "enum": INTENTS},
        "confidence": {"type": "number"},
        "reply": {"type": "string"},
    }
)


class Output(BaseModel):
    intent: str
    confidence: float = 0.5
    reply: str = ""


def build_user(ctx: dict) -> str:
    return f"Conversation state: {json.dumps(ctx['state'])}\nShopper message: {ctx['text']}"


def mock(ctx: dict) -> dict:
    text = ctx["text"].lower()
    state = ctx["state"]

    def result(intent: str, confidence: float, reply: str) -> dict:
        return {"intent": intent, "confidence": confidence, "reply": reply}

    if re.search(r"start over|new shop|forget that|another week|next week|instead i have", text):
        return result("new_request", 0.8, "Starting a fresh request.")
    if state.get("draft_stage"):
        if re.fullmatch(r"\s*(?:please )?(?:cancel|cancel (?:it|that|this|the request|this request)|never mind|nevermind)[.!]?\s*", text):
            return result("cancel_request", 0.95, "Cancelled — your previous confirmed constraints are unchanged.")
        if re.search(r"\bactually\b|\b(?:change|correct|make it|remove|drop|instead)\b", text):
            return result("correct_request", 0.9, "Updating your draft.")
    if state.get("pending_questions"):
        return result("clarify_answer", 0.85, "Thanks — updating your request.")
    if state.get("draft_stage") and not re.search(r"^(hi|hello|hey|thanks|thank you)\b", text):
        return result("correct_request", 0.85, "Updating your draft.")
    if re.search(r"\bis (?:now )?(?:a )?(?:vegetarian|vegan|halal|coeliac|celiac|lactose intolerant|allergic)"
                 r"|\bhas (?:a |an )?(?:mild |severe )?[a-z ]*allerg|\bjoin(?:s|ed) (?:us|the household)"
                 r"|\badd (?:a |an )?(?:new )?(?:member|person|child|kid|teen|senior)\b|\badd [a-z]+, (?:a|an) (?:child|teen|adult|senior)"
                 r"|\b(?:allergy|allergies|diet) (?:for|of) [a-z]+", text):
        return result("edit_household", 0.8, "Updating your household profile.")
    if re.search(r"why (?:is|are) .+ cheaper|cheaper at \w|how much (?:is|are|does)|price of ", text):
        return result("price_question", 0.8, "Checking that price across stores.")
    if not state.get("has_basket"):
        if re.search(r"\$|\d+ (meals|days|people)|budget|week|allerg|intoleran|vegan|vegetarian|meals?", text):
            return result("new_request", 0.85, "Let me work out what you need.")
        if re.search(r"^(hi|hello|hey|thanks|thank you)", text):
            return result("chat", 0.7, "")
        return result("new_request", 0.55, "Let me work out what you need.")
    if re.search(r"\bwhy\b|how did you|explain", text):
        return result("explain", 0.8, "Here's how I built it.")
    if re.search(r"meal ?plan|plan (my |the |some )?meals|recipes?|what (can|should) i cook", text):
        return result("meal_plan", 0.85, "Planning meals from your basket.")
    if re.search(r"compare|cheaper elsewhere|which store|retailer|savings?", text):
        return result("compare_prices", 0.8, "Comparing retailers.")
    if re.search(r"replace|swap|instead|remove|drop|add|more|less|fewer|cheaper|without|no more|under \$|make it \$|budget (?:of|to) \$", text):
        return result("edit_basket", 0.85, "Updating your basket.")
    return result("chat", 0.5, "")


TASK = Task(name="classify_intent", system=SYSTEM, build_user=build_user, mock=mock, schema=SCHEMA, output_model=Output)
