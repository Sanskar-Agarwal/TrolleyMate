"""Do not silently choose a product or apply only half a requested edit."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.catalogue import matching_items
from app.workflows.basket_editing import edit


def test_ambiguous_target_asks_before_mutating():
    def item(pid, name):
        return SimpleNamespace(product=SimpleNamespace(id=pid, name=name, brand="", category="dairy",
                               substitution_group="milk", tags=["milk"]), product_id=pid, quantity=1)
    basket = SimpleNamespace(id=1, session_id=1, items=[item(1, "Oat Milk 1L"), item(2, "Soy Milk 1L")])
    agent = MagicMock()
    agent.think.return_value.data = {"operations": [{"op": "remove", "target": "milk"}], "budget_change": None}
    result = edit(agent, basket, "remove milk")
    assert result["status"] == "clarify"
    assert "Oat Milk" in result["question"] and "Soy Milk" in result["question"]
    assert len(basket.items) == 2
    assert len(matching_items(basket, "Soy Milk 1L")) == 1
