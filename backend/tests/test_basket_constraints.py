"""KAN-3: hard quantity constraints must never be silently relaxed."""

import pytest

from tests.test_basket_flow import confirmed_session

from app.domain import Product, Retailer
from app.domain.requests_constraints import ConstraintSet
from app.optimisation import BasketOptimiser, Requirements, strategy_for
from app.optimisation.types import Candidate


def candidate():
    product = Product(id=1, sku="TEST", name="Test staple", category="carb", servings=4,
                      nutrition={"kcal": 1000}, tags=[], substitution_group="rice",
                      perishable=False, prep_minutes_per_serving=5)
    return Candidate(product, Retailer(id=1, name="Test shop"), 3.0)


@pytest.mark.parametrize("goal", ["lowest_cost", "best_nutrition", "least_waste", "fastest_cook", "balanced"])
@pytest.mark.parametrize("lower,upper,message", [
    ({1: 2}, {1: 1}, "Minimum quantity"),
    ({2: 1}, {}, "unavailable"),
    ({1: 1.5}, {}, "whole numbers"),
    ({}, {1: -1}, "whole numbers"),
])
def test_invalid_quantity_contract_is_rejected(goal, lower, upper, message):
    req = Requirements.from_constraints(ConstraintSet.from_payload(
        {"budget": 100, "household_size": 1, "days": 1, "meals_per_day": 1}))
    result = BasketOptimiser().solve(req, strategy_for(goal), [candidate()], min_qty=lower, max_qty=upper)
    assert not result.feasible
    assert message in result.message


def test_replaced_basket_cannot_be_accepted(client, riley):
    sid = confirmed_session(client, riley, "$100 for 3 days, dinner only for myself")
    old = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=riley).json()["basket"]
    client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=riley)
    assert client.post(f"/api/baskets/{old['id']}/accept", headers=riley).status_code == 400


def test_changed_constraints_require_a_rebuilt_basket(client, riley):
    sid = confirmed_session(client, riley, "$100 for 3 days, dinner only for myself")
    basket = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=riley).json()["basket"]
    rid = client.post(f"/api/sessions/{sid}/requests", json={"text": "$80 for 5 days, dinner only"}, headers=riley).json()["intake"]["request_id"]
    assert client.post(f"/api/requests/{rid}/confirm", headers=riley).status_code == 200
    assert client.post(f"/api/baskets/{basket['id']}/accept", headers=riley).status_code == 400
