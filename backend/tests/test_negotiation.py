"""P03 (1.2.4, UC-03): infeasibility negotiation. Known answers on the P01 fixture catalogue for the
minimum budget and the most feasible days; both options re-solve only after the shopper confirms;
rejection and cancellation leave the confirmed constraints and the mandatory restrictions in place;
a solver timeout is not treated as infeasibility."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.domain import AuditRecord, Basket, ConstraintSetRecord, ShoppingRequest
from app.domain.requests_constraints import ConstraintSet
from app.llm.tasks.negotiation_message import TASK as NEGOTIATION_MESSAGE
from app.optimisation import BasketOptimiser, Requirements, strategy_for
from app.workflows import negotiation
from tests.optimiser_spike import load_cases
from tests.test_basket_flow import confirmed_session

CATALOGUE = load_cases()[0].candidates  # all six fixture products
INFEASIBLE_WEEK = "$8 for the week, three meals a day for myself"
ALEX_INFEASIBLE = "$30 for the week, three meals a day for two of us"


class StubAgent:
    """Just enough of an agent for analyse(): the deterministic message, no database."""

    def __init__(self):
        self.contexts = []

    def think(self, task, ctx):
        self.contexts.append(ctx)
        return SimpleNamespace(data=NEGOTIATION_MESSAGE.mock(ctx))

    def log(self, *args, **kwargs):
        pass


def analyse(payload: dict, goal: str = "lowest_cost", candidates=CATALOGUE) -> tuple[dict, Requirements]:
    cs = ConstraintSet.from_payload(payload)
    req = Requirements.from_constraints(cs)
    agent = StubAgent()
    info = negotiation.analyse(agent, SimpleNamespace(id=1), cs, req, strategy_for(goal), candidates, "infeasible")
    return info, req


def feasible(payload: dict, goal: str = "lowest_cost", **change) -> bool:
    req = Requirements.from_constraints(ConstraintSet.from_payload({**payload, **change}))
    return BasketOptimiser().solve(req, strategy_for(goal), CATALOGUE).feasible


# --- Known answers on the fixture catalogue (docs/OPTIMISER_CONTRACT.md §6) -----------------------

# One person, two main meals a day for two days: kcal 2200, protein 88 g, 8 veg serves, 4 protein and
# 4 carb servings. The veg cap needs both vegetables ($5.00). Two lentils + penne give only 69 g of
# protein, so add rice: lentils ×2 + rice + penne + broccoli + carrots = $14.50 (94 g); swapping a
# lentil for chicken instead costs $15.00. One day is the $7.00 fixture basket.
TWO_DAYS = {"household_size": 1, "days": 2, "meals_per_day": 2, "budget": 10.0}


def test_known_answer_minimum_budget_and_most_days():
    assert not feasible(TWO_DAYS)
    info, req = analyse(TWO_DAYS)
    options = {o["id"]: o for o in info["options"]}
    assert options["increase_budget"]["budget"] == 14.50
    assert info["shortfall"] == 4.50
    assert options["reduce_days"]["days"] == 1 and options["reduce_days"]["person_meals"] == 2
    assert not info["timed_out"] and info["blocked_roles"] == []
    assert info["person_meals"] == req.person_meals == 4

    # Each option is exactly right: it fits, and a cent less / one more day does not.
    assert feasible(TWO_DAYS, budget=14.50) and not feasible(TWO_DAYS, budget=14.49)
    assert feasible(TWO_DAYS, days=1)


def test_known_answer_uses_the_shoppers_goal():
    """Best Nutrition raises the veg and protein bar, so its minimum budget is higher."""
    info, _ = analyse({**TWO_DAYS, "days": 1, "budget": 8.0}, "best_nutrition")
    option = next(o for o in info["options"] if o["id"] == "increase_budget")
    assert option["budget"] == 9.00  # the P01 fixture answer
    assert not any(o["id"] == "reduce_days" for o in info["options"])  # one day can't shrink


def test_explanation_states_both_options_and_keeps_restrictions():
    agent = StubAgent()
    cs = ConstraintSet.from_payload(TWO_DAYS)
    info = negotiation.analyse(agent, SimpleNamespace(id=1), cs, Requirements.from_constraints(cs),
                               strategy_for("lowest_cost"), CATALOGUE)
    facts = agent.contexts[0]
    assert facts["min_budget"] == 14.50 and facts["extra_needed"] == 4.50 and facts["max_meals"] == 2
    assert "$4.50 to $14.50" in info["message"] and "2 person-meals" in info["message"]
    assert "restrictions stay in place" in info["message"]


def test_no_budget_fixes_a_missing_role():
    no_protein = [c for c in CATALOGUE if c.role != "protein"]
    info, _ = analyse({**TWO_DAYS, "budget": 500.0}, candidates=no_protein)
    assert info["options"] == [] and info["blocked_roles"] == ["protein"]


def test_pins_and_reserved_budget_are_kept_while_searching():
    """Other hard constraints stay in force: a pinned product stays pinned, and money already
    spent outside the solver is added to the offered budget."""
    chicken = next(c for c in CATALOGUE if c.product.sku == "SPK-CHICKEN").product.id
    cs = ConstraintSet.from_payload({**TWO_DAYS, "days": 1, "budget": 7.0})
    req = Requirements.from_constraints(cs)
    info = negotiation.analyse(StubAgent(), SimpleNamespace(id=1), cs, replace(req, budget=5.0), strategy_for("lowest_cost"),
                               CATALOGUE, min_qty={chicken: 1}, reserve=2.0)
    option = next(o for o in info["options"] if o["id"] == "increase_budget")
    # Chicken pinned: chicken + penne + carrots = $10.00 for the solver (73 g protein), plus the $2.00 reserve.
    assert option["budget"] == 12.00 and info["budget"] == 7.00 and info["shortfall"] == 5.00


def test_a_timeout_while_negotiating_is_not_reported_as_blocked(monkeypatch):
    monkeypatch.setattr("app.optimisation.basket_optimiser.milp", lambda **_: SimpleNamespace(x=None, status=1, fun=None))
    info, _ = analyse(TWO_DAYS)
    assert info["timed_out"] and info["options"] == [] and info["blocked_roles"] == []
    assert "ran out of time" in info["message"]


# --- End to end through the API -------------------------------------------------------------------

def _infeasible(client, headers, text=INFEASIBLE_WEEK, goal="lowest_cost") -> tuple[int, dict]:
    sid = confirmed_session(client, headers, text)
    r = client.post(f"/api/sessions/{sid}/basket", json={"goal": goal}, headers=headers).json()
    assert r["status"] == "infeasible", r
    return sid, r["negotiation"]


def _active(sid: int) -> ConstraintSetRecord:
    with SessionLocal() as db:
        from app.domain import ShoppingSession

        session = db.get(ShoppingSession, sid)
        record = db.get(ConstraintSetRecord, session.active_constraint_set_id)
        db.expunge(record)
        return record


def _baskets(sid: int) -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(Basket).where(Basket.session_id == sid)).all())


def test_both_options_are_offered_and_nothing_is_solved_until_confirmed(client, riley):
    sid, neg = _infeasible(client, riley)
    ids = {o["id"] for o in neg["options"]}
    assert ids == {"increase_budget", "reduce_days"}
    assert neg["shortfall"] > 0 and neg["message"]
    assert _baskets(sid) == 0 and _active(sid).version == 1
    with SessionLocal() as db:
        assert db.scalar(select(ShoppingRequest).where(ShoppingRequest.session_id == sid)).status == "infeasible"


@pytest.mark.parametrize("option_id", ["increase_budget", "reduce_days"])
def test_confirming_an_option_re_solves_with_only_that_change(client, riley, option_id):
    sid, neg = _infeasible(client, riley)
    before = _active(sid).payload
    option = next(o for o in neg["options"] if o["id"] == option_id)
    choice = {"option_id": option_id, "budget": option.get("budget"), "days": option.get("days")}
    r = client.post(f"/api/sessions/{sid}/negotiate", json={k: v for k, v in choice.items() if v is not None}, headers=riley).json()
    assert r["status"] == "ok"
    after = _active(sid)
    assert after.version == 2 and after.origin == "negotiation"
    changed = {k for k in before.keys() | after.payload.keys() if before.get(k) != after.payload.get(k)}
    assert changed == ({"budget"} if option_id == "increase_budget" else {"days"})
    assert r["basket"]["total"] <= after.payload["budget"] + 0.01


def test_confirmation_trace_is_recorded_in_order(client, riley):
    sid, neg = _infeasible(client, riley)
    option = next(o for o in neg["options"] if o["id"] == "increase_budget")
    client.post(f"/api/sessions/{sid}/negotiate", json={"option_id": option["id"], "budget": option["budget"]}, headers=riley)
    with SessionLocal() as db:
        actions = [a.action for a in db.scalars(select(AuditRecord).where(AuditRecord.session_id == sid).order_by(AuditRecord.id))]
    # Offered → shopper confirmed → only then re-solved.
    offered, chosen = actions.index("infeasibility_negotiation"), actions.index("accept_tradeoff")
    assert offered < chosen < actions.index("optimise_basket")


def test_a_rejected_choice_that_still_does_not_fit_changes_nothing(client, riley):
    sid, neg = _infeasible(client, riley)
    r = client.post(f"/api/sessions/{sid}/negotiate", json={"budget": 9.0}, headers=riley).json()
    assert r["status"] == "infeasible"
    assert r["negotiation"]["options"] and r["negotiation"]["budget"] == 9.0  # fresh options for the new numbers
    assert _active(sid).version == 1 and _active(sid).payload["budget"] == 8 and _baskets(sid) == 0


def test_cancel_keeps_the_original_unfulfilled_request(client, riley):
    sid, _ = _infeasible(client, riley)
    r = client.post(f"/api/sessions/{sid}/negotiate/cancel", headers=riley)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "cancelled" and body["version"] == 1 and body["basket"] is None
    assert _active(sid).version == 1 and _baskets(sid) == 0
    with SessionLocal() as db:
        assert db.scalar(select(ShoppingRequest).where(ShoppingRequest.session_id == sid)).status == "infeasible"
        assert db.scalar(select(AuditRecord).where(AuditRecord.session_id == sid, AuditRecord.action == "cancel_negotiation"))


def test_negotiation_never_weakens_mandatory_restrictions(client, alex):
    sid, neg = _infeasible(client, alex, ALEX_INFEASIBLE, "balanced")
    # Restrictions aren't negotiable: the endpoint refuses them outright.
    sneaky = client.post(f"/api/sessions/{sid}/negotiate", json={"budget": 500, "restrictions": []}, headers=alex)
    assert sneaky.status_code == 422
    before = _active(sid).payload.get("restrictions")

    option = next(o for o in neg["options"] if o["id"] == "increase_budget")
    r = client.post(f"/api/sessions/{sid}/negotiate", json={"option_id": option["id"], "budget": option["budget"]}, headers=alex).json()
    assert r["status"] == "ok"
    assert _active(sid).payload.get("restrictions") == before
    names = {i["product"]["name"] for i in r["basket"]["items"]}
    assert not names & {"Full Cream Milk 2L", "Light Milk 2L", "Almond Milk 1L"}  # lactose, tree nuts
    assert all(i["compliance"] != "violation" for i in r["basket"]["items"])

    cancelled = client.post(f"/api/sessions/{sid}/negotiate/cancel", headers=alex).json()
    assert _active(sid).payload.get("restrictions") == before and cancelled["basket"]["id"] == r["basket"]["id"]


def test_an_unknown_option_is_refused(client, riley):
    sid, _ = _infeasible(client, riley)
    r = client.post(f"/api/sessions/{sid}/negotiate", json={"option_id": "drop_allergies", "budget": 50}, headers=riley)
    assert r.status_code == 400 and _active(sid).version == 1


def test_a_solver_timeout_offers_a_retry_not_a_negotiation(client, riley, monkeypatch):
    sid = confirmed_session(client, riley, "$80 for the week, two meals a day for myself")
    monkeypatch.setattr("app.optimisation.basket_optimiser.milp", lambda **_: SimpleNamespace(x=None, status=1, fun=None))
    r = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=riley).json()
    assert r["status"] == "timed_out" and "try again" in r["message"]
    assert "negotiation" not in r
    with SessionLocal() as db:
        assert db.scalar(select(ShoppingRequest).where(ShoppingRequest.session_id == sid)).status == "confirmed"
    monkeypatch.undo()
    assert client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=riley).json()["status"] == "ok"
