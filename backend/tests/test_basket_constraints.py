"""KAN-3: hard quantity constraints must never be silently relaxed."""

import pytest

from app.domain import Product, Retailer
from app.domain.requests_constraints import ConstraintSet
from app.optimisation import BasketOptimiser, Requirements, strategy_for
from app.optimisation.types import Candidate
from tests.test_basket_flow import confirmed_session


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


def _catalogue_pool(db):
    from sqlalchemy import select

    retailer = db.scalar(select(Retailer).limit(1))
    return [Candidate(p, retailer, 4.0) for p in db.scalars(select(Product)) if p.nutrition and p.nutrition.get("kcal")]


@pytest.mark.parametrize("name,nutrient", [("fibre_g", "fibre_g"), ("fiber", "fibre_g"), ("carbs", "carbs_g")])
def test_non_protein_nutrition_targets_are_enforced(client, name, nutrient):
    from app.core.db import SessionLocal

    payload = {"budget": 1000, "household_size": 2, "days": 7, "meals_per_day": 2}
    with SessionLocal() as db:
        pool = _catalogue_pool(db)
        baseline = BasketOptimiser().solve(Requirements.from_constraints(ConstraintSet.from_payload(payload)), strategy_for("lowest_cost"), pool)
        target = round(baseline.nutrition[nutrient] / 14 * 1.5, 1)  # per person per day, 50% above what we'd buy anyway
        req = Requirements.from_constraints(ConstraintSet.from_payload(
            {**payload, "nutritional_targets": [{"nutrient": name, "minimum_per_day": target}]}))
        result = BasketOptimiser().solve(req, strategy_for("lowest_cost"), pool)
    assert req.extra_minimums[nutrient] == pytest.approx(target * 14)
    assert result.feasible, result.message
    assert result.nutrition[nutrient] >= target * 14 - 0.1


def test_unsupported_nutrient_target_is_flagged_not_silently_kept(client, riley):
    sid = client.post("/api/sessions", headers=riley).json()["session"]["id"]
    rid = client.post(f"/api/sessions/{sid}/requests", json={"text": "$80 for the week, dinners for one"}, headers=riley).json()["intake"]["request_id"]
    patch = {"nutritional_targets": [{"nutrient": "iron_mg", "minimum_per_day": 18}, {"nutrient": "fiber", "minimum_per_day": 25}]}
    intake = client.post(f"/api/requests/{rid}/correct", json={"patch": patch}, headers=riley).json()["intake"]
    assert intake["draft"]["nutritional_targets"] == [{"nutrient": "fibre_g", "minimum_per_day": 25}]
    assert any("iron mg" in a for a in intake["draft"]["assumptions"])
