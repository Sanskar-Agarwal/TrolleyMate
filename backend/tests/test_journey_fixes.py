"""Regressions found while running the Week 13 demo script end to end (KAN-5)."""

from app.domain import Product, Retailer
from app.domain.requests_constraints import ConstraintSet
from app.optimisation import BasketOptimiser, Requirements, strategy_for
from app.optimisation.types import Candidate
from tests.test_basket_flow import _force_escalation_scenario, confirmed_session


def test_shopper_pin_can_exceed_the_soft_variety_cap(client):
    # Demo step 9: "replace the lentils with chicken" pins more chicken than the 40% variety
    # share of protein servings allows; the shopper's explicit pin must win over that soft rule.
    from sqlalchemy import select

    from app.core.db import SessionLocal

    with SessionLocal() as db:
        retailer = db.scalar(select(Retailer).limit(1))
        products = [p for p in db.scalars(select(Product)) if p.nutrition and p.nutrition.get("kcal")]
        pool = [Candidate(p, retailer, 4.0) for p in products]
        chicken = next(p for p in products if p.sku == "PRO-CHB-500")
        req = Requirements.from_constraints(ConstraintSet.from_payload(
            {"budget": 500, "household_size": 2, "days": 7, "meals_per_day": 2}))
        pinned = 4  # 16 servings against a cap of 0.4 x 28 = 11.2
        result = BasketOptimiser().solve(req, strategy_for("balanced"), pool, min_qty={chicken.id: pinned})
    assert result.feasible, result.message
    assert dict((c.product.id, q) for c, q in result.items)[chicken.id] >= pinned


def test_dietitian_decision_clears_held_notice_and_explanation_facts(client, alex, sam):
    sid = confirmed_session(client, alex, "$100 for the week, two meals a day")
    b = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=alex).json()["basket"]
    if not any(i["withheld"] for i in b["items"]):
        _force_escalation_scenario(b["id"])
    for case in client.get("/api/escalations", headers=sam).json()["cases"]:
        if case["basket_id"] != b["id"] or case["status"] == "resolved":
            continue
        client.post(f"/api/escalations/{case['id']}/begin", headers=sam)
        r = client.post(f"/api/escalations/{case['id']}/resolve", json={"decision": "passed", "note": "Checked."}, headers=sam)
        assert r.status_code == 200
        name = case["product"]
        after = client.get(f"/api/baskets/{b['id']}", headers=alex).json()
        assert not any(n.startswith(f"{name} is held") for n in after["notifications"])
        assert any(name in n and "confirmed safe" in n for n in after["notifications"])
        facts = client.get(f"/api/baskets/{b['id']}/explain", headers=alex).json()["facts"]
        assert name not in facts["withheld"]
        assert facts["total"] == after["total"]
        assert f"${after['total']:.2f}" in after["summary"]  # the summary is rewritten, not left on the old total


def test_dietitian_approval_is_not_reused_after_allergy_becomes_more_severe(client, alex, sam):
    # R02/M04: a "safe" decision reviewed against a moderate lactose intolerance says nothing
    # about a severe one, so the same product must be re-checked, not trusted.
    sid = confirmed_session(client, alex, "$100 for the week, two meals a day")
    b = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=alex).json()["basket"]
    if not any(i["withheld"] for i in b["items"]):
        _force_escalation_scenario(b["id"])
    case = next(c for c in client.get("/api/escalations", headers=sam).json()["cases"]
                if c["basket_id"] == b["id"] and c["status"] != "resolved")
    client.post(f"/api/escalations/{case['id']}/begin", headers=sam)
    client.post(f"/api/escalations/{case['id']}/resolve", json={"decision": "passed", "note": "ok"}, headers=sam)

    member = next(m for m in client.get("/api/households/me", headers=alex).json()["members"] if m["name"] == "Alex")
    stricter = [{"restriction": r["restriction"], "kind": r["kind"], "severity": "severe"} for r in member["restrictions"]]
    r = client.put(f"/api/households/me/members/{member['id']}",
                   json={"name": "Alex", "age_group": member["age_group"], "restrictions": stricter}, headers=alex)
    assert r.status_code == 200, r.text

    from sqlalchemy import select

    from app.agents.context import AgentContext
    from app.core.db import SessionLocal
    from app.domain import Household, Product, User
    from app.llm import get_llm

    with SessionLocal() as db:
        household = db.scalar(select(Household).join(User).where(User.email == "alex@trolleymate.demo"))
        product = db.scalar(select(Product).where(Product.name == case["product"]))
        agent = AgentContext(db=db, llm=get_llm()).compliance
        finding = agent.screen_product(product, agent.restrictions_for(household, None), household.id)
    assert finding.status != "compliant"
    assert not any(f.get("kind") == "human_review" for f in finding.findings)


def test_protein_gap_repairs_suggest_protein_foods_first(client, alex):
    from sqlalchemy import select

    from app.agents.context import AgentContext
    from app.core.db import SessionLocal
    from app.domain import Basket, Household, Product, User
    from app.llm import get_llm

    sid = confirmed_session(client, alex, "$100 for the week, two meals a day")
    bid = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=alex).json()["basket"]["id"]
    with SessionLocal() as db:
        basket = db.get(Basket, bid)
        household = db.scalar(select(Household).join(User).where(User.email == "alex@trolleymate.demo"))
        gap = {"nutrient": "protein_g", "required": 1680, "provided": 1530, "short_by": 150}
        nutrition = {"gaps": [gap], "coverage": [{**gap, "met": False, "accepted": False}]}
        repairs = AgentContext(db=db, llm=get_llm()).compliance.nutrition_repairs(basket, nutrition, household, {})
        categories = [db.get(Product, r["product_id"]).category for r in repairs]
    assert repairs and categories[0] == "protein", categories


def test_pantry_additions_respect_budget_and_survive_later_edits(client, riley):
    # C04: extras added from chat are outside the solver, so they must still fit the budget and
    # must not vanish when the next edit rebuilds the basket.
    sid = confirmed_session(client, riley, "$7 for 1 day, dinner only for myself")
    b = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=riley).json()["basket"]
    refused = client.post(f"/api/baskets/{b['id']}/edit", json={"text": "add olive oil"}, headers=riley).json()
    assert refused["status"] == "conflict"
    assert client.get(f"/api/baskets/{b['id']}", headers=riley).json()["total"] == b["total"]

    sid = confirmed_session(client, riley, "$40 for 3 days, dinner only for myself")
    b = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=riley).json()["basket"]
    b = client.post(f"/api/baskets/{b['id']}/edit", json={"text": "add olive oil"}, headers=riley).json()["basket"]
    r = client.post(f"/api/baskets/{b['id']}/edit", json={"text": "add chocolate"}, headers=riley).json()
    assert r["status"] == "ok"
    names = {i["product"]["name"] for i in r["basket"]["items"]}
    assert {"Olive Oil 500ml", "Dark Chocolate 45g"} <= names
    assert r["basket"]["total"] <= 40
    assert f"${r['basket']['total']:.2f}" in r["basket"]["summary"]
    facts = client.get(f"/api/baskets/{r['basket']['id']}/explain", headers=riley).json()["facts"]
    assert facts["total"] == r["basket"]["total"]


def test_explanation_nutrition_follows_an_accepted_swap(client, riley):
    sid = confirmed_session(client, riley, "$80 for the week, two meals a day for myself")
    b = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=riley).json()["basket"]
    for item in b["items"]:
        sub = client.post(f"/api/baskets/{b['id']}/items/{item['id']}/substitute", json={}, headers=riley).json()["substitution"]
        if sub["status"] == "pending":
            break
    else:
        return
    client.post(f"/api/substitutions/{sub['id']}/accept", headers=riley)
    after = client.get(f"/api/baskets/{b['id']}", headers=riley).json()
    facts = client.get(f"/api/baskets/{b['id']}/explain", headers=riley).json()["facts"]
    assert facts["nutrition"] == after["nutrition"]["provided"]
    assert facts["nutrition_adequate"] == after["nutrition"]["adequate"]
