"""P01: the optimiser interface contract (docs/OPTIMISER_CONTRACT.md) on deterministic fixtures."""

from types import SimpleNamespace

import pytest

from app.optimisation import STRATEGIES, BasketOptimiser, strategy_for
from tests.optimiser_spike import load_cases, resolve_at, run_case

CASES = {c.id: c for c in load_cases()}


def test_feasible_fixture_known_answer():
    case = CASES["feasible_lowest_cost"]
    r = run_case(case)
    assert r.result.feasible and not r.result.timed_out
    assert r.result.total == pytest.approx(case.expect["total"])
    assert r.items == case.expect["items"]


@pytest.mark.parametrize("case_id", ["infeasible_budget", "infeasible_budget_best_nutrition"])
def test_infeasible_budget_reports_min_budget(case_id):
    case = CASES[case_id]
    r = run_case(case)
    assert not r.result.feasible and not r.result.timed_out
    assert r.result.message == "No basket satisfies every constraint."
    assert r.min_budget == pytest.approx(case.expect["min_budget"])
    assert r.min_budget - case.req.budget == pytest.approx(case.expect["shortfall"])
    # The offered minimum really is enough under the shopper's own goal...
    assert resolve_at(case, case.goal, r.min_budget).feasible
    # ...and is the minimum: a cent less still fails.
    assert not resolve_at(case, case.goal, r.min_budget - 0.01).feasible


def test_infeasible_when_role_missing():
    r = run_case(CASES["infeasible_no_protein"])
    assert not r.result.feasible and not r.result.timed_out
    assert r.min_budget is None  # no budget fixes a missing role


@pytest.mark.parametrize("goal", list(STRATEGIES))
def test_every_goal_respects_budget_and_targets(goal):
    case = CASES["every_goal_feasible"]
    r = run_case(case, goal)
    assert r.result.feasible
    assert r.result.total <= case.req.budget + 1e-6
    target = strategy_for(goal).adjust(case.req)
    n = r.result.nutrition
    assert n["kcal"] >= target.kcal and n["protein_g"] >= target.protein_g and n["veg_serves"] >= target.veg_serves
    servings = {role: sum(c.product.servings * q for c, q in r.result.items if c.role == role) for role in ("protein", "carb")}
    assert servings["protein"] >= target.protein_servings and servings["carb"] >= target.carb_servings


@pytest.mark.parametrize("goal", list(STRATEGIES))
def test_solver_is_deterministic(goal):
    case = CASES["every_goal_feasible"]
    assert run_case(case, goal).items == run_case(case, goal).items


def test_timeout_is_not_infeasibility(monkeypatch):
    monkeypatch.setattr("app.optimisation.basket_optimiser.milp", lambda **_: SimpleNamespace(x=None, status=1, fun=None))
    case = CASES["feasible_lowest_cost"]
    result = BasketOptimiser().solve(case.req, strategy_for(case.goal), case.candidates)
    assert not result.feasible and result.timed_out
    assert result.message == "Timed out before finding a basket."
