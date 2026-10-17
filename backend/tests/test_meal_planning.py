"""KAN-4 meal scheduling and stock allocation regression coverage."""

from types import SimpleNamespace

import pytest

from app.domain.requests_constraints import ConstraintSet
from app.optimisation import Requirements
from app.services import meal_planner
from app.services.meal_planner import Stock, _allocate, _closest_missing
from app.services.meal_schedule import meal_schedule


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
    assert _allocate([["breakfast"], ["milk"]], [milk, oats], 1) == [oats, milk]
    assert milk.remaining == 1 and oats.remaining == 1


def test_missing_ingredients_account_for_shared_stock():
    oats = Stock(1, "Oats", {"breakfast"}, 1, 30, False)
    recipe = {"name": "Breakfast", "needs": [["breakfast"], ["breakfast"]]}
    assert _allocate(recipe["needs"], [oats], 1) is None
    assert _closest_missing([recipe], [oats], 1)["missing_tags"] == ["breakfast"]


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
