"""1.2.2/1.2.3: baskets are bought for meals that can actually be cooked, sized for who's eating."""

import pytest

from app.domain import Product, Retailer
from app.optimisation.types import Candidate
from tests.test_basket_flow import confirmed_session


def _plan(client, headers, text, goal):
    sid = confirmed_session(client, headers, text)
    b = client.post(f"/api/sessions/{sid}/basket", json={"goal": goal}, headers=headers).json()["basket"]
    assert client.post(f"/api/baskets/{b['id']}/accept", headers=headers).status_code == 200
    return b, client.post(f"/api/baskets/{b['id']}/meal-plan", headers=headers).json()["meal_plan"]


@pytest.mark.parametrize("goal", ["balanced", "lowest_cost", "best_nutrition"])
def test_a_lunch_and_dinner_basket_covers_every_meal(client, riley, goal):
    # Before: breakfast oats counted as the "carb" for dinners, so 8 of 14 meals had nothing to cook.
    b, plan = _plan(client, riley, "$80 for the week, two meals a day for myself", goal)
    assert plan["planned"] == plan["requested"] == 14, plan["missing"]
    assert "Rolled Oats 1kg" not in {i["product"]["name"] for i in b["items"]}


def test_breakfast_foods_never_count_as_dinner_carbs():
    def candidate(name, tags):
        return Candidate(Product(id=1, sku=name, name=name, category="carb", servings=10, nutrition={}, tags=tags,
                                 substitution_group=name, perishable=False, prep_minutes_per_serving=1), Retailer(id=1, name="R"), 1.0)

    assert candidate("Rolled Oats", ["oats", "breakfast"]).role is None
    assert candidate("Rolled Oats", ["oats", "breakfast"]).is_breakfast
    assert candidate("Penne", ["pasta"]).role == "carb"


def test_a_child_is_sized_as_a_smaller_portion(client, alex):
    hh = client.get("/api/households/me", headers=alex).json()
    r = client.post("/api/households/me/members", json={"name": "Kit", "age_group": "child", "restrictions": []}, headers=alex)
    assert r.status_code in (200, 201), r.text
    sid = client.post("/api/sessions", headers=alex).json()["session"]["id"]
    draft = client.post(f"/api/sessions/{sid}/requests", json={"text": "$150 for the week, two meals a day"}, headers=alex).json()["intake"]["draft"]
    assert draft["household_size"] == len(hh["members"]) + 1
    assert draft["portions"] == 2.6
    assert any("adult serves" in a for a in draft["assumptions"])


def test_portions_scale_requirements():
    from app.domain.requests_constraints import ConstraintSet
    from app.optimisation import Requirements

    base = {"budget": 100, "household_size": 3, "days": 7, "meals_per_day": 2}
    full = Requirements.from_constraints(ConstraintSet.from_payload(base))
    child = Requirements.from_constraints(ConstraintSet.from_payload({**base, "portions": 2.6}))
    assert full.person_meals == 42 and child.person_meals == 37
    assert child.protein_g < full.protein_g
