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


@pytest.mark.parametrize("reason", ["timeout", "solver_error"])
def test_retryable_rebuild_preserves_accepted_basket_and_confirmed_request(client, riley, monkeypatch, reason):
    from app.optimisation.types import OptimisationResult

    sid = confirmed_session(client, riley, "$100 for 3 days, dinner only for myself")
    old = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=riley).json()["basket"]
    assert client.post(f"/api/baskets/{old['id']}/accept", headers=riley).status_code == 200
    before = client.get(f"/api/sessions/{sid}", headers=riley).json()
    monkeypatch.setattr(BasketOptimiser, "solve", lambda *args, **kwargs: OptimisationResult(
        False, message="Search incomplete.", failure_reason=reason))
    response = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=riley)
    assert response.status_code == 200
    assert response.json()["status"] == "retryable"
    assert response.json()["reason"] == reason
    assert "Retry" in response.json()["message"]
    after = client.get(f"/api/sessions/{sid}", headers=riley).json()
    assert after["basket"]["id"] == old["id"] and after["basket"]["status"] == "accepted"
    assert after["constraints"] == before["constraints"]
    from app.core.db import SessionLocal
    from app.domain import ShoppingSession
    with SessionLocal() as db:
        session = db.get(ShoppingSession, sid)
        assert all(r.status == "confirmed" for r in session.requests)


def test_pending_candidate_preserves_previous_accepted_basket(client, riley, monkeypatch):
    from app.agents.nutrition_compliance import NutritionComplianceAgent
    from app.domain.enums import ItemCompliance, VerdictStatus

    sid = confirmed_session(client, riley, "$100 for 3 days, dinner only for myself")
    old = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=riley).json()["basket"]
    assert client.post(f"/api/baskets/{old['id']}/accept", headers=riley).status_code == 200
    original_verify = NutritionComplianceAgent.verify

    def escalate(self, basket, *args, **kwargs):
        verdict = original_verify(self, basket, *args, **kwargs)
        basket.items[0].withheld = True
        basket.items[0].compliance = ItemCompliance.uncertain
        verdict.status = VerdictStatus.escalated
        return verdict

    monkeypatch.setattr(NutritionComplianceAgent, "verify", escalate)
    response = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=riley)
    pending = response.json()["basket"]
    assert pending["status"] == "pending_review"
    assert client.post(f"/api/baskets/{pending['id']}/accept", headers=riley).status_code == 400
    assert client.get(f"/api/baskets/{old['id']}", headers=riley).json()["status"] == "accepted"


def test_failed_verification_rolls_back_candidate_and_preserves_previous_basket(client, riley, monkeypatch):
    from app.agents.nutrition_compliance import NutritionComplianceAgent
    from app.domain.enums import VerdictStatus

    sid = confirmed_session(client, riley, "$100 for 3 days, dinner only for myself")
    old = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=riley).json()["basket"]
    assert client.post(f"/api/baskets/{old['id']}/accept", headers=riley).status_code == 200
    original_verify = NutritionComplianceAgent.verify

    def fail(self, basket, *args, **kwargs):
        verdict = original_verify(self, basket, *args, **kwargs)
        verdict.status = VerdictStatus.failed
        return verdict

    monkeypatch.setattr(NutritionComplianceAgent, "verify", fail)
    response = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=riley)
    assert response.status_code == 400
    assert "failed dietary verification" in response.json()["detail"]
    current = client.get(f"/api/sessions/{sid}", headers=riley).json()["basket"]
    assert current["id"] == old["id"] and current["status"] == "accepted"


def test_timeout_edit_reports_retry_without_claiming_constraint_conflict(client, riley, monkeypatch):
    from app.optimisation.types import OptimisationResult

    sid = confirmed_session(client, riley, "$100 for 3 days, dinner only for myself")
    old = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=riley).json()["basket"]
    assert client.post(f"/api/baskets/{old['id']}/accept", headers=riley).status_code == 200
    monkeypatch.setattr(BasketOptimiser, "solve", lambda *args, **kwargs: OptimisationResult(
        False, message="The search timed out before finding a valid basket.", failure_reason="timeout"))
    response = client.post(f"/api/baskets/{old['id']}/edit", json={"text": "add some chicken"}, headers=riley)
    assert response.status_code == 200
    assert response.json()["status"] == "conflict"
    assert "Retry" in response.json()["message"]
    assert "breaking" not in response.json()["message"]
    current = client.get(f"/api/sessions/{sid}", headers=riley).json()["basket"]
    assert current["id"] == old["id"] and current["status"] == "accepted"


def test_edit_summary_includes_added_and_preserved_pantry_total(client, riley):
    sid = confirmed_session(client, riley, "$100 for 3 days, dinner only for myself")
    basket = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=riley).json()["basket"]
    response = client.post(f"/api/baskets/{basket['id']}/edit", json={"text": "add peanut butter"}, headers=riley)
    assert response.json()["status"] == "ok", response.text
    added = response.json()["basket"]
    assert any(i["product"]["category"] == "pantry" for i in added["items"])
    assert f"${added['total']:.2f}" in added["summary"]
    response = client.post(f"/api/baskets/{added['id']}/edit", json={"text": "add some chicken"}, headers=riley)
    assert response.json()["status"] == "ok", response.text
    changed = response.json()["basket"]
    assert f"${changed['total']:.2f}" in changed["summary"]
    explanation = client.get(f"/api/baskets/{changed['id']}/explain", headers=riley).json()
    assert explanation["facts"]["total"] == changed["total"]
