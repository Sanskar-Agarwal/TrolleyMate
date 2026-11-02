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


def test_add_rice_then_pasta_preserves_existing_items(client, riley):
    from tests.test_basket_flow import confirmed_session
    sid = confirmed_session(client, riley, "$200 for the week, two meals a day for myself")
    basket = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=riley).json()["basket"]
    for text in ("add basmati rice", "add pasta but dont remove anything"):
        before = {i["product"]["id"]: i["quantity"] for i in basket["items"]}
        result = client.post(f"/api/baskets/{basket['id']}/edit", json={"text": text}, headers=riley).json()
        assert result["status"] == "ok", result
        basket = result["basket"]
        after = {i["product"]["id"]: i["quantity"] for i in basket["items"]}
        assert all(after.get(pid, 0) >= qty for pid, qty in before.items())
        assert not result["diff"]["removed"]
    names = str(basket["items"]).lower()
    assert "basmati" in names and "spaghetti" in names


def test_negated_removal_is_not_parsed_as_a_remove():
    from app.llm.tasks.parse_edit import mock
    for text in ("add pasta but dont remove anything", "add pasta but don't remove anything", "add pasta without removing anything"):
        plan = mock({"text": text, "items": ["Basmati Rice 1kg"]})
        assert plan["operations"] == [{"op": "add", "target": None, "replacement": "pasta"}]
