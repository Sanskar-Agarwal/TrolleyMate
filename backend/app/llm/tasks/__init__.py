"""Registry of every LLM task. To add one: create a module with a `TASK` and list it here."""

from app.llm.tasks import (
    assess_ingredient,
    chat_reply,
    classify_intent,
    explain,
    extract_constraints,
    household_edit,
    market_insight,
    meal_plan_notes,
    negotiation_message,
    parse_edit,
    supply_information,
    tradeoff,
)
from app.llm.tasks._base import Task

TASKS: dict[str, Task] = {
    m.TASK.name: m.TASK
    for m in (
        assess_ingredient,
        chat_reply,
        classify_intent,
        explain,
        extract_constraints,
        household_edit,
        market_insight,
        meal_plan_notes,
        negotiation_message,
        parse_edit,
        supply_information,
        tradeoff,
    )
}
