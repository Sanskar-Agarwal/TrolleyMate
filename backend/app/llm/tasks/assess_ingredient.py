"""UC-06 — judge whether a vague label ingredient may hide a restricted allergen. Owner: Compliance."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

from app.llm.tasks._base import Task, obj

SYSTEM = """You are the AI Nutrition & Compliance agent of Trolley Mate.
A product label lists a vague ingredient term. Judge whether it may contain or be
derived from the restricted allergen/diet item. Use the guidance notes provided; if they
don't cover the term, say so in your reasoning and stay conservative. Be conservative: food safety comes
first. risk is "none" only when the term essentially never contains it.
confidence is how sure you are of your risk call (0-1). Keep reasoning to one sentence."""

SCHEMA = obj(
    {
        "risk": {"type": "string", "enum": ["none", "possible", "likely"]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    }
)


class Output(BaseModel):
    # Enforced here as well as in SCHEMA: not every server honours the schema, and a risk word outside
    # these three ("High", "unknown") must fail validation, never be read as "none" (KAN-23).
    risk: Literal["none", "possible", "likely"]
    confidence: float
    reasoning: str

    @field_validator("risk", mode="before")
    @classmethod
    def _lower(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


def build_user(ctx: dict) -> str:
    notes = "\n".join(f"- {n['text']} (risk: {n['risk']})" for n in ctx.get("guidance", [])) or "- none found"
    return (
        f"Product: {ctx['product']}\nIngredient term on the label: {ctx['ingredient']}\n"
        f"Restriction to check: {ctx['restriction']}\nGuidance notes ({ctx.get('source', 'retrieved')}):\n{notes}"
    )


# Conservative lookup used offline. A term that is neither listed here nor flagged by a guidance note
# is judged "none" at 0.97: enough to clear it in offline mode, but never when it stands in for a live
# model that failed (the agent then treats the term as unchecked).
_KNOWN = {
    ("natural flavours", "milk"): ("possible", 0.6, "Natural flavours can be dairy-derived (e.g. butter or milk solids)."),
    ("natural flavours", "lactose"): ("possible", 0.6, "Dairy-derived flavours can carry lactose."),
    ("natural flavours", "tree_nuts"): ("possible", 0.55, "Nut extracts are sometimes declared only as natural flavour."),
    ("spices", "gluten"): ("possible", 0.6, "Spice blends can contain wheat-based anti-caking agents."),
    ("spices", "wheat"): ("possible", 0.6, "Spice blends can contain wheat-based anti-caking agents."),
    ("emulsifier (471)", "vegan"): ("possible", 0.55, "E471 can be made from animal or plant fats."),
    ("emulsifier (471)", "vegetarian"): ("possible", 0.55, "E471 can be made from animal fats."),
    ("emulsifier (471)", "halal"): ("possible", 0.55, "E471 can be derived from pork fat."),
    ("vegetable oil", "peanuts"): ("possible", 0.7, "Unspecified vegetable oil can include peanut oil."),
}


def mock(ctx: dict) -> dict:
    key = (ctx["ingredient"].lower(), ctx["restriction"])
    # Offline, the retrieved guidance decides first; a named "likely" source is a clear signal.
    for note in ctx.get("guidance", []):
        if note["risk"] in ("likely", "possible") and key not in _KNOWN:
            return {"risk": note["risk"], "confidence": 0.85 if note["risk"] == "likely" else 0.6, "reasoning": note["text"]}
    if key in _KNOWN:
        risk, confidence, reasoning = _KNOWN[key]
    else:
        risk, confidence, reasoning = "none", 0.97, f"'{ctx['ingredient']}' is not a typical source of {ctx['restriction'].replace('_', ' ')}."
    return {"risk": risk, "confidence": confidence, "reasoning": reasoning}


TASK = Task(name="assess_ingredient", system=SYSTEM, build_user=build_user, mock=mock, schema=SCHEMA, output_model=Output)
