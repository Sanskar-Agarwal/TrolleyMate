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
