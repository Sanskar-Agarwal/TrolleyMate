"""KAN-21: nutritional coverage checks (1.2.11, UC-02 ext 4b) — sufficient and insufficient baskets,
scaled households, compliant candidate repairs, and the trace of an explicitly accepted exception."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.agents.context import AgentContext
from app.core.db import SessionLocal
from app.domain import AuditRecord, Basket, Household, Product, User
from app.llm import get_llm
from app.optimisation.types import Requirements
from app.services.compliance_verdict import NutritionCoverage, NutritionRepair
from tests.test_basket_flow import confirmed_session

TARGETS = {"kcal", "protein_g", "veg_serves", "staple_serves"}
ONE_PERSON = "$70 for the week, two meals a day for myself"


def built_basket(client, headers, text: str = ONE_PERSON) -> dict:
    sid = confirmed_session(client, headers, text)
    r = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=headers).json()
    assert r["status"] == "ok", r
    return r["basket"]


def drop(basket_id: int, category: str) -> None:
    """Take every item of one category out of the basket, to open a gap."""
    with SessionLocal() as db:
        b = db.get(Basket, basket_id)
        for item in [i for i in b.items if i.product.category == category]:
            b.items.remove(item)
        b.recalc_total()
        db.commit()


def coverage(client, headers, basket_id: int) -> tuple[NutritionCoverage, list[NutritionRepair]]:
    r = client.get(f"/api/baskets/{basket_id}/nutrition", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    return NutritionCoverage.model_validate(body["nutrition"]), [NutritionRepair.model_validate(x) for x in body["repairs"]]


def accept(client, headers, basket_id: int, nutrients: list[str], note: str = ""):
    return client.post(f"/api/baskets/{basket_id}/nutrition/exceptions", json={"nutrients": nutrients, "note": note}, headers=headers)


# --- Sufficient and insufficient baskets -----------------------------------------


def test_sufficient_basket_meets_every_target_with_nothing_to_repair(client, riley):
    b = built_basket(client, riley)
    report, repairs = coverage(client, riley, b["id"])
    assert {c.nutrient for c in report.coverage} == TARGETS
    assert report.adequate and all(c.met for c in report.coverage) and not report.gaps
    assert repairs == []


@pytest.mark.parametrize(("category", "nutrient"), [("veg", "veg_serves"), ("carb", "staple_serves"), ("protein", "protein_g")])
def test_insufficient_basket_names_the_gap_and_candidate_repairs(client, riley, category, nutrient):
    b = built_basket(client, riley)
    drop(b["id"], category)
    report, repairs = coverage(client, riley, b["id"])

    assert not report.adequate
    gap = next(g for g in report.gaps if g.nutrient == nutrient)
    assert gap.short_by > 0
    options = [r for r in repairs if r.nutrient == nutrient]
    assert options and options[0].closes_gap and options[0].adds >= gap.short_by
    with SessionLocal() as db:
        held = {i.product_id for i in db.get(Basket, b["id"]).items}
    assert not held & {r.product_id for r in options}  # suggests something new, changes nothing


def test_repairs_never_break_a_mandatory_restriction(client, alex):
    b = built_basket(client, alex, "$120 for the week, two meals a day")
    drop(b["id"], "protein")
    drop(b["id"], "carb")
    _, repairs = coverage(client, alex, b["id"])
    assert repairs
    with SessionLocal() as db:
        user = db.query(User).filter_by(email="alex@trolleymate.demo").one()
        household = db.query(Household).filter_by(shopper_id=user.id).one()
        agent = AgentContext(db=db, llm=get_llm(), user=user).compliance
        restrictions = agent.restrictions_for(household, None)
        assert {r["restriction"] for r in restrictions} >= {"lactose", "tree_nuts"}
        for r in repairs:
            assert agent.screen_product(db.get(Product, r.product_id), restrictions, household.id).status == "compliant", r.product


# --- Scaled households -------------------------------------------------------------


def _req(size: int = 1, days: int = 7, meals: int = 2) -> Requirements:
    return Requirements.from_constraints(SimpleNamespace(payload={"household_size": size, "days": days, "meals_per_day": meals}))


@pytest.mark.parametrize(("size", "days"), [(2, 7), (4, 7), (3, 3)])
def test_targets_scale_with_household_size_and_days(size, days):
    one, scaled = _req(), _req(size, days)
    factor = size * days / 7
    for field in ("kcal", "protein_g", "veg_serves", "carb_servings"):
        assert getattr(scaled, field) == pytest.approx(getattr(one, field) * factor), field


def test_breakfast_adds_energy_but_not_main_meal_targets():
    two, three = _req(meals=2), _req(meals=3)  # 3 a day adds breakfast to lunch and dinner
    assert three.kcal == pytest.approx(two.kcal * 1.5)
    assert (three.protein_g, three.veg_serves, three.carb_servings) == (two.protein_g, two.veg_serves, two.carb_servings)


def test_basket_adequate_for_one_falls_short_for_four(client, riley):
    b = built_basket(client, riley)
    with SessionLocal() as db:
        basket = db.get(Basket, b["id"])
        agent = AgentContext(db=db, llm=get_llm()).compliance
        assert agent.assess_nutrition(basket, _req(1))["adequate"]
        four = NutritionCoverage.model_validate(agent.assess_nutrition(basket, _req(4)))
    assert not four.adequate
    assert {g.nutrient for g in four.gaps} == TARGETS


# --- Explicitly accepted exceptions ----------------------------------------------


def test_accepted_exception_marks_adequacy_and_leaves_a_trace(client, riley):
    b = built_basket(client, riley)
    drop(b["id"], "veg")
    gaps = [g.nutrient for g in coverage(client, riley, b["id"])[0].gaps]
    assert "veg_serves" in gaps
    r = accept(client, riley, b["id"], ["veg_serves"], "We grow our own greens.")
    assert r.status_code == 200, r.text

    nutrition = NutritionCoverage.model_validate(r.json()["basket"]["nutrition"])
    veg = next(c for c in nutrition.coverage if c.nutrient == "veg_serves")
    assert not veg.met and veg.accepted
    assert nutrition.adequate == (gaps == ["veg_serves"])  # every other gap still has to be met or accepted
    (exception,) = nutrition.exceptions
    assert (exception.nutrient, exception.accepted_by, exception.note) == ("veg_serves", "Riley Brooks", "We grow our own greens.")
    assert any(t["action"] == "accept_nutrition_exception" for t in r.json()["trace"])

    with SessionLocal() as db:
        riley_id = db.query(User).filter_by(email="riley@trolleymate.demo").one().id
        record = db.scalars(select(AuditRecord).where(
            AuditRecord.action == "accept_nutrition_exception", AuditRecord.basket_id == b["id"])).one()
    assert record.actor_user_id == riley_id
    assert record.payload["exceptions"][0]["short_by"] == exception.short_by
    assert "Allergen and dietary restrictions are unchanged" in record.rationale

    _, repairs = coverage(client, riley, b["id"])
    assert not [x for x in repairs if x.nutrient == "veg_serves"]  # an accepted gap isn't pushed again

    others = [n for n in gaps if n != "veg_serves"]
    if others:
        r = accept(client, riley, b["id"], others)
        assert NutritionCoverage.model_validate(r.json()["basket"]["nutrition"]).adequate


@pytest.mark.parametrize("nutrients", [["protein_g"], [], ["vitamin_c"]], ids=["met-target", "nothing", "unknown"])
def test_only_a_current_gap_can_be_accepted(client, riley, nutrients):
    b = built_basket(client, riley)
    assert accept(client, riley, b["id"], nutrients).status_code == 400


def test_only_the_shopper_can_accept_their_gap(client, riley, alex, maya):
    b = built_basket(client, riley)
    drop(b["id"], "veg")
    assert accept(client, alex, b["id"], ["veg_serves"]).status_code == 404  # not their basket
    assert accept(client, maya, b["id"], ["veg_serves"]).status_code == 403  # the founder can see it, not decide it


def test_exception_does_not_cover_a_bigger_gap(client):
    def basket(veg_serves):
        product = SimpleNamespace(nutrition={"veg_serves": veg_serves}, category="veg", servings=1)
        return [SimpleNamespace(product=product, quantity=1, withheld=False)]

    req = SimpleNamespace(kcal=0, protein_g=0, veg_serves=16, carb_servings=0, extra_minimums={})
    b = SimpleNamespace(id=None, session_id=None, notes={}, items=basket(10))
    with SessionLocal() as db:
        user = db.query(User).filter_by(email="riley@trolleymate.demo").one()
        agent = AgentContext(db=db, llm=get_llm(), user=user).compliance
        assert agent.accept_nutrition_exception(b, req, ["veg_serves"])["adequate"]  # accepted: short by 6
        b.items = basket(4)  # the basket changed: now short by 12
        report = agent.assess_nutrition(b, req)
    assert not report["adequate"]
    assert [c["accepted"] for c in report["coverage"] if c["nutrient"] == "veg_serves"] == [False]


def test_accepting_a_gap_never_waives_compliance(client, alex):
    b = built_basket(client, alex, "$120 for the week, two meals a day")
    if not any(i["withheld"] for i in b["items"]):
        pytest.skip("No uncertain item in this basket to hold back.")
    drop(b["id"], "veg")
    gaps = [g.nutrient for g in coverage(client, alex, b["id"])[0].gaps]
    after = accept(client, alex, b["id"], gaps).json()["basket"]
    assert after["nutrition"]["adequate"]
    assert after["status"] == "pending_review" and any(i["withheld"] for i in after["items"])
    assert client.post(f"/api/baskets/{b['id']}/accept", headers=alex).status_code == 400


def test_a_rebuilt_basket_starts_without_exceptions(client, riley):
    b = built_basket(client, riley)
    drop(b["id"], "veg")
    assert accept(client, riley, b["id"], ["veg_serves"]).status_code == 200
    fresh = client.post(f"/api/sessions/{b['session_id']}/basket", json={"goal": "lowest_cost"}, headers=riley).json()["basket"]
    assert fresh["id"] != b["id"] and fresh["nutrition"]["exceptions"] == []


# --- Basket acceptance gate --------------------------------------------------------


def accept_basket(client, headers, basket_id: int):
    return client.post(f"/api/baskets/{basket_id}/accept", headers=headers)


def test_a_basket_with_an_open_gap_cannot_be_accepted(client, riley):
    b = built_basket(client, riley)
    drop(b["id"], "veg")
    r = accept_basket(client, riley, b["id"])
    assert r.status_code == 400
    assert "Meet or accept the nutrition gaps" in r.text and "vegetables short by" in r.text
    assert client.get("/api/sessions/current", headers=riley).json()["basket"]["status"] == "verified"


def test_accepting_every_gap_unlocks_basket_acceptance(client, riley):
    b = built_basket(client, riley)
    drop(b["id"], "veg")
    gaps = [g.nutrient for g in coverage(client, riley, b["id"])[0].gaps]
    if len(gaps) > 1:  # accepting only some of the gaps isn't enough
        assert accept(client, riley, b["id"], gaps[:1]).status_code == 200
        assert accept_basket(client, riley, b["id"]).status_code == 400
    assert accept(client, riley, b["id"], gaps).status_code == 200
    r = accept_basket(client, riley, b["id"])
    assert r.status_code == 200, r.text
    assert r.json()["basket"]["status"] == "accepted"


def test_the_gate_checks_the_basket_as_it_is_now(client, riley):
    # A stale "adequate" summary can't let an inadequate basket through...
    b = built_basket(client, riley)
    drop(b["id"], "veg")  # the stored summary still says adequate
    assert accept_basket(client, riley, b["id"]).status_code == 400

    # ...and a stale "gaps found" summary can't block an adequate one.
    b = built_basket(client, riley)
    with SessionLocal() as db:
        basket = db.get(Basket, b["id"])
        stale = {**basket.notes["nutrition"], "adequate": False}
        basket.notes = {**basket.notes, "nutrition": stale}
        db.commit()
    shown = client.get("/api/sessions/current", headers=riley).json()["basket"]["nutrition"]
    assert shown["adequate"]  # every basket read reports nutrition as the basket is now
    assert accept_basket(client, riley, b["id"]).status_code == 200


def test_a_basket_saved_before_a_requirements_field_existed_still_loads(client, riley):
    b = built_basket(client, riley)
    with SessionLocal() as db:
        basket = db.get(Basket, b["id"])
        stored = basket.notes["nutrition"]
        older = {k: v for k, v in basket.notes["requirements"].items() if k != "carb_servings"}
        basket.notes = {**basket.notes, "requirements": older}  # as if saved before carb_servings existed
        db.commit()

    r = client.get("/api/sessions/current", headers=riley)
    assert r.status_code == 200, r.text
    assert r.json()["basket"]["nutrition"] == stored  # falls back to the summary saved at build time
    assert client.post(f"/api/baskets/{b['id']}/verify", headers=riley).status_code == 200
    assert client.get(f"/api/baskets/{b['id']}/nutrition", headers=riley).status_code == 400  # says why, doesn't crash
    assert accept_basket(client, riley, b["id"]).status_code == 200  # the gate can't trap an older basket


def test_contract_rejects_an_acceptance_without_a_recorded_exception():
    with pytest.raises(ValidationError, match="recorded exception"):
        NutritionCoverage(
            adequate=True, provided={}, required={}, targets="t", suggestions=[],
            coverage=[{"nutrient": "veg_serves", "required": 16, "provided": 4, "coverage_pct": 25, "met": False, "accepted": True}],
            gaps=[{"nutrient": "veg_serves", "required": 16, "provided": 4, "short_by": 12}],
        )


@pytest.mark.parametrize("nutrient", ["fibre_g", "carbs_g", "fat_g"])
def test_custom_target_is_checked_against_current_basket(client, riley, nutrient):
    b = built_basket(client, riley)
    with SessionLocal() as db:
        basket = db.get(Basket, b["id"])
        req = _req()
        req.extra_minimums = {nutrient: 100000}
        agent = AgentContext(db=db, llm=get_llm()).compliance
        report = agent.assess_nutrition(basket, req)
        assert not report["adequate"]
        assert any(g["nutrient"] == nutrient for g in report["gaps"])
