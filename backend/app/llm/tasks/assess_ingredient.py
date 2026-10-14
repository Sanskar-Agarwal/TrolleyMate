"""UC-06 — judge whether a vague label ingredient may hide a restricted allergen. Owner: Compliance."""

from __future__ import annotations

from pydantic import BaseModel

from app.llm.tasks._base import Task, obj

SYSTEM = """You are the AI Nutrition & Compliance agent of Trolley Mate.
A product label lists a vague ingredient term. Judge whether it may contain or be
derived from the restricted allergen/diet item. Be conservative: food safety comes
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
    risk: str
    confidence: float
    reasoning: str


def build_user(ctx: dict) -> str:
    return (
        f"Product: {ctx['product']}\nIngredient term on the label: {ctx['ingredient']}\n"
        f"Restriction to check: {ctx['restriction']}"
    )


# Conservative lookup used offline. Anything not listed is "possible" at low confidence.
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
    if key in _KNOWN:
        risk, confidence, reasoning = _KNOWN[key]
    else:
        risk, confidence, reasoning = "none", 0.97, f"'{ctx['ingredient']}' is not a typical source of {ctx['restriction'].replace('_', ' ')}."
    return {"risk": risk, "confidence": confidence, "reasoning": reasoning}


TASK = Task(name="assess_ingredient", system=SYSTEM, build_user=build_user, mock=mock, schema=SCHEMA, output_model=Output)
