"""KAN-3: deterministic goal choices and solver failure boundaries."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from app.domain import Product, Retailer
from app.domain.requests_constraints import ConstraintSet
from app.optimisation import BasketOptimiser, Requirements, strategy_for
from app.optimisation.types import Candidate

GOALS = ["lowest_cost", "best_nutrition", "least_waste", "fastest_cook", "balanced"]


def goal_fixture():
    shop = Retailer(id=1, name="Fixture shop")
    values = [
        ("Cheap", 1, 30, True, 10, 0),
        ("Keeps", 1.2, 15, False, 10, 0),
        ("Quick", 2.4, 1, False, 10, 0),
        ("Nutrients", 1.6, 20, False, 100, 20),
    ]
    candidates = [Candidate(Product(id=i, sku=name, name=name, category="protein", servings=1,
                                    nutrition={"protein_g": protein, "fibre_g": fibre}, tags=["protein"],
                                    perishable=perishable, prep_minutes_per_serving=prep), shop, price)
                  for i, (name, price, prep, perishable, protein, fibre) in enumerate(values, 1)]
    unsafe = Candidate(Product(id=5, sku="UNSAFE", name="Excluded", category="protein", servings=1,
                               nutrition={"protein_g": 200, "fibre_g": 100}, tags=["protein"],
                               perishable=False, prep_minutes_per_serving=0), shop, 0.01, compliance="violation")
    req = Requirements(1, 1, 1, 2.5, 1, 1, 0, 0, 0, 0, 1, 0, 0)
    return req, candidates + [unsafe]


@pytest.mark.parametrize("goal,expected", list(zip(GOALS, ["Cheap", "Nutrients", "Keeps", "Quick", "Keeps"], strict=True)))
def test_goals_make_evidenced_choices_without_trading_budget_or_compliance(goal, expected):
    req, candidates = goal_fixture()
    result = BasketOptimiser().solve(req, strategy_for(goal), candidates)
    assert result.feasible, result.message
    assert [(c.product.name, q) for c, q in result.items] == [(expected, 1)]
    assert result.total <= req.budget
    assert all(c.compliance == "compliant" for c, _ in result.items)
    impossible = BasketOptimiser().solve(replace(req, budget=0.5), strategy_for(goal), candidates)
    assert not impossible.feasible
    assert impossible.failure_reason is None


@pytest.mark.parametrize("status,reason", [(1, "timeout"), (2, None), (4, "solver_error")])
def test_timeout_and_solver_failure_are_not_proven_infeasibility(monkeypatch, status, reason):
    monkeypatch.setattr("app.optimisation.basket_optimiser.milp", lambda **kwargs: SimpleNamespace(x=None, status=status))
    req, candidates = goal_fixture()
    result = BasketOptimiser().solve(req, strategy_for("lowest_cost"), candidates)
    assert not result.feasible
    assert result.failure_reason == reason


@pytest.mark.parametrize("quantities,valid", [([1, 0, 0, 0], True), ([0, 0, 0, 0], False), ([0, 0, 2, 0], False)])
def test_timed_out_incumbent_must_meet_all_hard_constraints(monkeypatch, quantities, valid):
    monkeypatch.setattr("app.optimisation.basket_optimiser.milp",
                        lambda **kwargs: SimpleNamespace(x=np.array(quantities), status=1))
    req, candidates = goal_fixture()
    result = BasketOptimiser().solve(req, strategy_for("lowest_cost"), candidates)
    assert result.feasible == valid
    assert result.failure_reason == (None if valid else "solver_error")


def test_child_rounding_cannot_steal_portions_from_main_meals():
    req = Requirements.from_constraints(ConstraintSet.from_payload(
        {"household_size": 1, "portions": 0.6, "days": 1, "meals_per_day": 3, "budget": 100}))
    assert req.breakfast_meals >= 0.6
    assert req.main_meals >= 1.2
    assert req.protein_servings >= 1.2 and req.carb_servings >= 1.2


def test_explicit_per_person_target_is_not_reduced_by_child_portion_factor():
    req = Requirements.from_constraints(ConstraintSet.from_payload(
        {"household_size": 3, "portions": 2.6, "days": 2, "meals_per_day": 1, "budget": 100,
         "nutritional_targets": [{"nutrient": "protein_g", "minimum_per_day": 120},
                                 {"nutrient": "fibre_g", "minimum_per_day": 30}]}))
    assert req.protein_g == 720
    assert req.extra_minimums["fibre_g"] == 180
