"""KAN-4 meal scheduling and stock allocation regression coverage."""

from types import SimpleNamespace

import pytest

from app.domain.requests_constraints import ConstraintSet
from app.optimisation import Requirements
from app.services import meal_planner
from app.services.meal_planner import Stock, _allocate, _closest_missing
from app.services.meal_schedule import meal_schedule
from tests.test_basket_flow import confirmed_session


@pytest.mark.parametrize("rate", [0.5, 1, 1.5, 2, 2.5, 3, 4, 5])
def test_basket_and_plan_agree_on_meal_counts(rate):
    schedule = meal_schedule(3, rate)
    req = Requirements.from_constraints(ConstraintSet.from_payload(
        {"household_size": 2, "days": 3, "meals_per_day": rate, "budget": 100}))
    assert req.person_meals == 2 * sum(map(len, schedule))
    assert req.main_meals + req.breakfast_meals == req.person_meals


def test_fractional_average_is_distributed_instead_of_rounded_daily():
    assert [len(day) for day in meal_schedule(4, 1.5)] == [2, 1, 2, 1]



def test_allocation_backtracks_when_flexible_slot_uses_unique_ingredient():
    milk = Stock(1, "Milk", {"milk", "breakfast"}, 1, 3, True)
    oats = Stock(2, "Oats", {"breakfast"}, 1, 30, False)
    assert {a.stock.name: a.servings for a in _allocate([["breakfast"], ["milk"]], [milk, oats], 1)} == {"Oats": 1, "Milk": 1}
    assert milk.remaining == 1 and oats.remaining == 1


def test_missing_ingredients_account_for_shared_stock():
    oats = Stock(1, "Oats", {"breakfast"}, 1, 30, False)
    recipe = {"name": "Breakfast", "needs": [["breakfast"], ["breakfast"]]}
    assert _allocate(recipe["needs"], [oats], 1) is None
    assert _closest_missing([recipe], [oats], 1)["missing_tags"] == ["breakfast"]


def test_partial_packs_combine_without_double_counting_flexible_slots():
    milk = Stock(1, "Milk", {"milk", "breakfast"}, 0.6, 3, True)
    oats = Stock(2, "Oats", {"breakfast"}, 0.4, 30, False)
    grain = Stock(3, "Grain", {"breakfast"}, 0.2, 30, False)
    allocation = _allocate([["breakfast"], ["milk"]], [milk, oats, grain], 0.6)
    assert {a.stock.name: a.servings for a in allocation} == pytest.approx({"Milk": 0.6, "Oats": 0.4, "Grain": 0.2})
    assert _allocate([["breakfast"], ["milk"]], [milk, oats, grain], 0.7) is None


def item(i, tag, servings, *, life=30, perishable=False):
    return SimpleNamespace(id=i, quantity=1, withheld=False, product=SimpleNamespace(
        name=f"{tag}-{i}", tags=[tag], category=tag, servings=servings, shelf_life_days=life, perishable=perishable))


def test_optional_extra_does_not_starve_later_required_meal(monkeypatch):
    monkeypatch.setattr(meal_planner, "load_recipes", lambda: [
        {"id": "plate", "name": "Plate", "meal_type": "main", "minutes": 5,
         "needs": [["carb"]], "optional": [["carb"]]}])
    result = meal_planner.plan(SimpleNamespace(items=[item(1, "carb", 2)]), 1, 2, 1)
    assert result["planned"] == 2
    assert all(not d["meals"][0]["optional"] for d in result["days"])
    assert result["leftovers"] == []


def test_child_portions_are_fractional_and_all_consumption_is_accounted_for(monkeypatch):
    monkeypatch.setattr(meal_planner, "load_recipes", lambda: [
        {"id": "plate", "name": "Plate", "meal_type": "main", "minutes": 5, "needs": [["carb"]]}])
    basket = SimpleNamespace(items=[item(1, "carb", 1), item(2, "carb", 1)])
    result = meal_planner.plan(basket, 1, 3, 1, portions=0.6)
    assert result["planned"] == 3
    assert result["portions_per_meal"] == 0.6
    consumed = {}
    for day in result["days"]:
        meal = day["meals"][0]
        assert meal["servings"] == 1
        assert sum(i["servings"] for i in meal["ingredients"]) == pytest.approx(0.6)
        for ingredient in meal["ingredients"]:
            consumed[ingredient["name"]] = consumed.get(ingredient["name"], 0) + ingredient["servings"]
    assert all(value <= 1 for value in consumed.values())
    assert sum(leftover["servings_left"] for leftover in result["leftovers"]) == pytest.approx(0.2)
    assert len(result["reused"]) == 2


def test_same_meal_repeated_ingredient_is_not_cross_meal_reuse(monkeypatch):
    monkeypatch.setattr(meal_planner, "load_recipes", lambda: [
        {"id": "plate", "name": "Plate", "meal_type": "main", "minutes": 5,
         "needs": [["carb"], ["carb"]]}])
    result = meal_planner.plan(SimpleNamespace(items=[item(1, "carb", 2)]), 1, 1, 1)
    assert result["reused"] == []
    assert result["days"][0]["meals"][0]["ingredients"] == [{"name": "carb-1", "servings": 2}]


@pytest.mark.parametrize("goal,expected", [("fastest_cook", "quick"), ("least_waste", "fresh")])
def test_meal_goal_uses_recipe_time_and_required_perishable_quantities(monkeypatch, goal, expected):
    monkeypatch.setattr(meal_planner, "load_recipes", lambda: [
        {"id": "quick", "name": "Quick", "meal_type": "main", "minutes": 5, "needs": [["carb"]]},
        {"id": "fresh", "name": "Fresh", "meal_type": "main", "minutes": 30, "needs": [["veg"]]}])
    basket = SimpleNamespace(goal=goal, items=[item(1, "carb", 1), item(2, "veg", 1, life=1, perishable=True)])
    result = meal_planner.plan(basket, 1, 1, 1)
    assert result["days"][0]["meals"][0]["recipe_id"] == expected
    assert result["total_minutes"] == (5 if expected == "quick" else 30)
    assert result["goal"] == goal


def test_planner_does_not_use_expired_or_withheld_stock(monkeypatch):
    monkeypatch.setattr(meal_planner, "load_recipes", lambda: [
        {"id": "plate", "name": "Plate", "meal_type": "main", "minutes": 5, "needs": [["veg"]]}])
    product = SimpleNamespace(name="Spinach", tags=["veg"], category="veg", servings=4,
                              shelf_life_days=1, perishable=True)
    basket = SimpleNamespace(items=[SimpleNamespace(id=1, product=product, quantity=1, withheld=False)])
    result = meal_planner.plan(basket, 1, 2, 1)
    assert result["planned"] == 1
    assert result["days"][1]["meals"][0]["recipe"] is None
    assert result["expired_unused"] == [{"name": "Spinach", "servings_left": 3}]
    basket.items[0].withheld = True
    assert meal_planner.plan(basket, 1, 2, 1)["planned"] == 0


def test_optional_ingredients_are_consumed_once(monkeypatch):
    monkeypatch.setattr(meal_planner, "load_recipes", lambda: [
        {"id": "plate", "name": "Plate", "meal_type": "main", "minutes": 5,
         "needs": [["carb"]], "optional": [["veg"]]}])
    def item(i, tag, servings):
        return SimpleNamespace(id=i, quantity=1, withheld=False, product=SimpleNamespace(
            name=tag, tags=[tag], category=tag, servings=servings, shelf_life_days=30, perishable=False))
    result = meal_planner.plan(SimpleNamespace(items=[item(1, "carb", 2), item(2, "veg", 1)]), 1, 2, 1)
    assert result["days"][0]["meals"][0]["optional"] == ["veg"]
    assert result["days"][1]["meals"][0]["optional"] == []
    assert result["leftovers"] == []



def test_meal_plan_requires_acceptance_and_uses_basket_only(client, riley):
    sid = confirmed_session(client, riley, "$100 for 3 days, dinner only for myself")
    b = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=riley).json()["basket"]
    assert client.post(f"/api/baskets/{b['id']}/meal-plan", headers=riley).status_code == 400
    assert client.post(f"/api/baskets/{b['id']}/accept", headers=riley).status_code == 200
    response = client.post(f"/api/baskets/{b['id']}/meal-plan", headers=riley)
    assert response.status_code == 200, response.text
    plan = response.json()["meal_plan"]
    names = {i["product"]["name"] for i in b["items"] if not i["withheld"]}
    assert plan["requested"] == 3
    for day in plan["days"]:
        for meal in day["meals"]:
            assert set(meal.get("uses", []) + meal.get("optional", [])) <= names
    assert client.get(f"/api/baskets/{b['id']}", headers=riley).json()["total"] == b["total"]


def test_plan_for_changed_stock_is_hidden(client, riley):
    from app.core.db import SessionLocal
    from app.domain import Basket

    sid = confirmed_session(client, riley, "$100 for 3 days, dinner only for myself")
    b = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=riley).json()["basket"]
    client.post(f"/api/baskets/{b['id']}/accept", headers=riley)
    assert client.post(f"/api/baskets/{b['id']}/meal-plan", headers=riley).status_code == 200
    with SessionLocal() as db:
        basket = db.get(Basket, b["id"])
        basket.items[0].quantity += 1
        db.commit()
    assert client.get(f"/api/baskets/{b['id']}/meal-plan", headers=riley).status_code == 404
    assert client.get(f"/api/sessions/{sid}", headers=riley).json()["meal_plan"] is None


def test_plan_for_changed_constraints_is_hidden(client, riley):
    sid = confirmed_session(client, riley, "$100 for 3 days, dinner only for myself")
    b = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=riley).json()["basket"]
    assert client.post(f"/api/baskets/{b['id']}/accept", headers=riley).status_code == 200
    assert client.post(f"/api/baskets/{b['id']}/meal-plan", headers=riley).status_code == 200
    assert client.get(f"/api/baskets/{b['id']}/meal-plan", headers=riley).status_code == 200

    request = client.post(f"/api/sessions/{sid}/requests",
                          json={"text": "$100 for 4 days, dinner only for myself"}, headers=riley)
    assert request.status_code == 200, request.text
    rid = request.json()["intake"]["request_id"]
    confirmed = client.post(f"/api/requests/{rid}/confirm", headers=riley)
    assert confirmed.status_code == 200, confirmed.text

    # Confirming constraints leaves the old basket accepted, but its plan is stale.
    assert client.get(f"/api/baskets/{b['id']}", headers=riley).json()["status"] == "accepted"
    assert client.get(f"/api/baskets/{b['id']}/meal-plan", headers=riley).status_code == 404
    assert client.get(f"/api/sessions/{sid}", headers=riley).json()["meal_plan"] is None


def test_partial_day_schedule_keeps_exact_negotiated_meal_count():
    assert meal_schedule(2, 3, meal_count=4) == [["Breakfast", "Lunch", "Dinner"], ["Breakfast"]]
    with pytest.raises(ValueError):
        meal_schedule(2, 3, meal_count=7)
