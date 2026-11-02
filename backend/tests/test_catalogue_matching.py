"""Specific chat requests must not silently become weaker catalogue matches."""

import pytest

from app.core.db import SessionLocal
from app.services.catalogue import find_products
from tests.test_basket_flow import confirmed_session


@pytest.mark.parametrize("description,expected", [
    ("almond milk", {"Almond Milk 1L"}),
    ("full cream milk", {"Full Cream Milk 2L"}),
])
def test_specific_catalogue_lookup_keeps_only_the_strongest_matches(client, description, expected):
    with SessionLocal() as db:
        assert {p.name for p in find_products(db, description, limit=10)} == expected


def test_generic_milk_lookup_keeps_safe_and_unsafe_options(client):
    with SessionLocal() as db:
        names = {p.name for p in find_products(db, "milk", limit=20)}
    assert {"Almond Milk 1L", "Full Cream Milk 2L", "Lactose Free Milk 2L"} <= names


def _alex_basket(client, alex):
    sid = confirmed_session(client, alex, "$150 for 5 days, dinner only")
    response = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=alex)
    assert response.status_code == 200 and response.json()["status"] == "ok", response.text
    return sid, response.json()["basket"]


def test_unsafe_exact_chat_addition_is_declined_without_changing_basket(client, alex):
    sid, before = _alex_basket(client, alex)
    constraints = client.get(f"/api/sessions/{sid}", headers=alex).json()["constraints"]
    response = client.post(f"/api/sessions/{sid}/chat", json={"text": "Add almond milk"}, headers=alex)
    assert response.status_code == 200, response.text
    result = response.json()["response"]
    assert result["kind"] == "edit" and result["edit"]["status"] == "conflict"
    assert "almond milk" in result["reply"].casefold() and "safe" in result["reply"]
    assert "almonds (tree nuts)" in result["reply"]
    state = client.get(f"/api/sessions/{sid}", headers=alex).json()
    assert state["basket"]["id"] == before["id"]
    assert state["basket"]["items"] == before["items"]
    assert state["basket"]["total"] == before["total"]
    assert state["constraints"] == constraints


def test_generic_chat_addition_can_choose_a_safe_milk(client, alex):
    sid, _ = _alex_basket(client, alex)
    response = client.post(f"/api/sessions/{sid}/chat", json={"text": "Add milk"}, headers=alex)
    assert response.status_code == 200, response.text
    result = response.json()["response"]
    assert result["edit"]["status"] == "ok", result
    assert "added Lactose Free Milk 2L" in result["edit"]["applied"]
    state = client.get(f"/api/sessions/{sid}", headers=alex).json()
    milk = next(i for i in state["basket"]["items"] if i["product"]["name"] == "Lactose Free Milk 2L")
    assert milk["compliance"] == "compliant" and not milk["withheld"]
    assert not {"Almond Milk 1L", "Full Cream Milk 2L"} & {i["product"]["name"] for i in state["basket"]["items"]}
