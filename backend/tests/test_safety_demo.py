"""KAN-24: the safety demo segment in docs/SAFETY_DEMO.md, run step by step as it is presented, once
for every weekday. The seed prices specials by weekday, so the basket changes from day to day; the
segment must work whatever day the demo falls on (1.2.10 hidden allergens; UC-06 ext 2a and the
3.1.6.1 failure scenario: an uncertain item stays withheld while its review is unresolved)."""

from datetime import date, datetime, timedelta

import pytest

import app.seed as seed
from app.core.db import SessionLocal, reset_db
from tests.conftest import login
from tests.test_basket_flow import confirmed_session

SHOP = "$120 for the week, two meals a day"
COELIAC_SHOP = "Feed a family of four for the week on $150, three meals a day. One of us is coeliac."
HELD = "Value Chicken Schnitzel 1kg"
# Next week, so the seeded quotes are never stale and refreshed at today's prices.
NEXT_MONDAY = date.today() + timedelta(days=7 - date.today().weekday())


def _seeded_as_if(day: date):
    class SeedDay(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(day.year, day.month, day.day, 10, 0, 0)
    return SeedDay


@pytest.fixture(params=range(7), ids=["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
def demo(request, monkeypatch, client):
    """The demo seed priced as on one weekday, and a signed-in client for each demo account."""
    reset_db()
    with monkeypatch.context() as m:
        m.setattr(seed, "datetime", _seeded_as_if(NEXT_MONDAY + timedelta(days=request.param)))
        with SessionLocal() as db:
            seed.seed_all(db)
            db.commit()
    yield client, {who: login(client, f"{who}@trolleymate.demo") for who in ("alex", "sam", "maya")}


def test_hidden_allergens_are_refused_and_the_uncertain_item_stays_unresolved(demo):
    client, as_ = demo
    alex, sam, maya = as_["alex"], as_["sam"], as_["maya"]

    # 1 — Alex's shop: Jamie's severe tree-nut allergy and Alex's lactose intolerance apply.
    sid = confirmed_session(client, alex, SHOP)
    built = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=alex).json()
    assert built["status"] == "ok"
    basket = built["basket"]
    assert {"Full Cream Milk 2L", "Almond Milk 1L"} <= {e["product"] for e in basket["excluded"]}

    # 2 — hidden allergens: each request is refused, naming what's hidden, and nothing else is added.
    for ask, hidden in [
        ("add honey muesli bars", ["whey powder", "almonds"]),  # a snack bar hiding dairy and nuts
        ("add sugar free mints", ["sweetener (966)"]),          # lactitol, made from lactose, behind an E-number
        ("add basil pesto", ["pine nuts"]),                     # inside the pesto: a composite ingredient
    ]:
        r = client.post(f"/api/baskets/{basket['id']}/edit", json={"text": ask}, headers=alex).json()
        assert r["status"] == "conflict" and "isn't safe for your household" in r["message"], (ask, r)
        assert all(word in r["message"] for word in hidden), (ask, r["message"])

    # 3 — unresolved uncertainty: the schnitzel's ingredient list is missing, so it is held for a dietitian.
    basket = client.get(f"/api/baskets/{basket['id']}", headers=alex).json()
    held = next(i for i in basket["items"] if i["product"]["name"] == HELD)
    assert held["withheld"] and held["compliance"] == "uncertain"
    assert basket["status"] == "pending_review"
    assert abs(basket["total"] - sum(i["line_total"] for i in basket["items"] if not i["withheld"])) < 0.01
    case = next(c for c in basket["cases"] if c["product"] == HELD)
    assert case["assigned_to"] == "Dr Sam Patel"

    # 4 — the dietitian asks for the label; the agent can only say it's missing. No decision is made.
    assert client.post(f"/api/escalations/{case['id']}/begin", headers=sam).status_code == 200
    asked = client.post(f"/api/escalations/{case['id']}/request-info", json={"question": "Is there a full ingredient list?"},
                        headers=sam).json()["case"]
    assert [t["from"] for t in asked["thread"]] == ["reviewer", "agent"] and asked["status"] == "under_review"

    # 5 — still unresolved: the item stays held and out of the total, and the basket can't be accepted.
    basket = client.get(f"/api/baskets/{basket['id']}", headers=alex).json()
    assert next(i for i in basket["items"] if i["product"]["name"] == HELD)["withheld"]
    accept = client.post(f"/api/baskets/{basket['id']}/accept", headers=alex)
    assert accept.status_code == 400 and "pending review" in accept.json()["detail"]
    queue = client.get("/api/escalations?status=open", headers=maya).json()["cases"]
    assert any(c["id"] == case["id"] and c["is_open"] for c in queue)
    audit = client.get(f"/api/audit?basket_id={basket['id']}", headers=maya).json()
    assert any(a["action"] == "raise_escalation" and a["confidence"] == 0.4 for a in audit)


def test_hidden_gluten_is_shown_in_what_was_left_out(demo):
    """The optional extra: a coeliac request leaves out grains and sausages, with the hidden ingredient named."""
    client, as_ = demo
    sid = confirmed_session(client, as_["alex"], COELIAC_SHOP)
    built = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=as_["alex"]).json()
    assert built["status"] == "ok"
    reasons = {e["product"]: e["findings"][0]["detail"] for e in built["basket"]["excluded"]}
    assert reasons["Pork Sausages 500g"] == "Contains wheat rusk (gluten)"
    assert reasons["Pearl Barley 500g"] == "Contains barley (gluten)"
    assert reasons["Couscous 500g"] == "Contains durum wheat semolina (gluten)"
