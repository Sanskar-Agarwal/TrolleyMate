"""P02 (1.2.5, UC-04): smart substitution with a stated trade-off. Swaps come from the price and
compliance interfaces, are applied only on acceptance, declined swaps are remembered for the session,
unsafe candidates never reach the shopper, and "no alternative" is reported."""

import pytest
from sqlalchemy import select

from app.agents.context import AgentContext
from app.core.db import SessionLocal
from app.domain import BasketItem, DietaryProfile, Household, PriceQuote, Product, ShoppingSession, Substitution, User
from app.domain.enums import ItemCompliance, RestrictionKind, Severity
from app.llm import get_llm
from tests.test_basket_flow import confirmed_session

WEEK = "$80 for the week, two meals a day for myself"
ALEX_WEEK = "$120 for the week, two meals a day"
# Alex is lactose intolerant and Jamie is allergic to tree nuts; oat milk's safety is unconfirmed.
UNSAFE_FOR_ALEX = {"Full Cream Milk 2L", "Light Milk 2L", "Almond Milk 1L", "Oat Milk 1L"}


def build(client, headers, text=WEEK) -> dict:
    sid = confirmed_session(client, headers, text)
    r = client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["basket"]


def propose(client, headers, basket_id, item_id, reason="user_requested"):
    return client.post(f"/api/baskets/{basket_id}/items/{item_id}/substitute", json={"reason": reason}, headers=headers)


def first_pending(client, headers, basket) -> tuple[dict, dict]:
    for item in basket["items"]:
        sub = propose(client, headers, basket["id"], item["id"]).json()["substitution"]
        if sub["status"] == "pending":
            return item, sub
    raise AssertionError("no swap offered for any item")


def item_in(basket: dict, item_id: int) -> dict | None:
    return next((i for i in basket["items"] if i["id"] == item_id), None)


def decline_until_exhausted(client, headers, basket_id, item_id, reason="user_requested") -> tuple[list[str], dict]:
    """Decline every offer for one item; return the offered names and the final (discarded) proposal."""
    offered = []
    for _ in range(80):
        r = propose(client, headers, basket_id, item_id, reason).json()
        sub = r["substitution"]
        if sub["status"] == "discarded":
            return offered, r
        offered.append(sub["replacement"]["name"])
        client.post(f"/api/substitutions/{sub['id']}/reject", headers=headers)
    raise AssertionError("substitutes never ran out")


def test_accept_applies_the_swap_with_its_trade_off(client, riley):
    basket = build(client, riley)
    item, sub = first_pending(client, riley, basket)
    assert sub["trade_off"] and sub["facts"]["retailer"] and sub["facts"]["quote_id"]
    assert sub["facts"]["saving"] == pytest.approx(round((item["pack_price"] - sub["replacement_price"]) * item["quantity"], 2))

    # Proposing changes nothing in the basket.
    unchanged = client.get(f"/api/baskets/{basket['id']}", headers=riley).json()
    assert item_in(unchanged, item["id"])["product"]["id"] == item["product"]["id"]
    assert unchanged["total"] == basket["total"]

    r = client.post(f"/api/substitutions/{sub['id']}/accept", headers=riley).json()
    assert r["substitution"]["status"] == "accepted"
    swapped = item_in(r["basket"], item["id"])
    assert swapped["product"]["id"] == sub["replacement"]["id"]
    assert swapped["pack_price"] == sub["replacement_price"]
    assert r["basket"]["total"] == pytest.approx(round(sum(i["line_total"] for i in r["basket"]["items"]), 2))
    assert r["basket"]["total"] == pytest.approx(basket["total"] - sub["facts"]["saving"])

    again = client.post(f"/api/substitutions/{sub['id']}/accept", headers=riley)
    assert again.status_code == 400  # a swap is applied once


def test_reject_keeps_the_original_and_is_remembered(client, riley):
    basket = build(client, riley)
    item, sub = first_pending(client, riley, basket)
    r = client.post(f"/api/substitutions/{sub['id']}/reject", headers=riley).json()
    assert r["substitution"]["status"] == "rejected"
    assert item_in(r["basket"], item["id"])["product"]["id"] == item["product"]["id"]
    assert r["basket"]["total"] == basket["total"]
    with SessionLocal() as db:
        session = db.get(ShoppingSession, basket["session_id"])
        assert [item["product"]["id"], sub["replacement"]["id"]] in session.rejected_swaps

    nxt = propose(client, riley, basket["id"], item["id"]).json()["substitution"]
    assert nxt["replacement"] is None or nxt["replacement"]["id"] != sub["replacement"]["id"]


def test_repeated_rejection_never_repeats_a_swap_then_reports_no_alternative(client, riley):
    basket = build(client, riley)
    item, sub = first_pending(client, riley, basket)
    client.post(f"/api/substitutions/{sub['id']}/reject", headers=riley)

    offered, last = decline_until_exhausted(client, riley, basket["id"], item["id"])
    names = [sub["replacement"]["name"], *offered]
    assert len(names) == len(set(names)), "a declined swap was offered again"

    final = last["substitution"]
    assert final["replacement"] is None and final["facts"]["no_alternative"]
    assert final["facts"]["declined_before"] == len(names)
    assert final["trade_off"].startswith("No suitable substitute") and "Keeping" in final["trade_off"]
    # A shopper-requested swap with no alternative leaves the item where it was.
    assert item_in(last["basket"], item["id"]) is not None

    # The memory is per session: a new session offers the first swap again.
    fresh = build(client, riley)
    again = next(i for i in fresh["items"] if i["product"]["id"] == item["product"]["id"])
    assert propose(client, riley, fresh["id"], again["id"]).json()["substitution"]["replacement"]["id"] == sub["replacement"]["id"]


def test_unsafe_candidates_never_reach_the_shopper(client, alex):
    basket = build(client, alex, ALEX_WEEK)
    with SessionLocal() as db:
        milk = db.scalar(select(Product).where(Product.name == "Lactose Free Milk 2L"))
        item = db.get(BasketItem, basket["items"][0]["id"])
        item.product_id = milk.id
        db.commit()
        item_id = item.id

    offered, _ = decline_until_exhausted(client, alex, basket["id"], item_id)
    assert "Soy Milk 1L" in offered  # the safe milk is offered
    assert not UNSAFE_FOR_ALEX & set(offered)

    with SessionLocal() as db:
        ctx = AgentContext(db=db, llm=get_llm())
        household = db.scalar(select(Household).join(User).where(User.email == "alex@trolleymate.demo"))
        restrictions = ctx.compliance.restrictions_for(household, None)
        products = db.scalars(select(Product).where(Product.name.in_(offered))).all()
        assert all(ctx.compliance.screen_product(p, restrictions, household.id).status == ItemCompliance.compliant for p in products)


def test_a_swap_that_became_unsafe_is_not_applied(client, riley):
    basket = build(client, riley)
    item, sub = first_pending(client, riley, basket)
    with SessionLocal() as db:
        # While the swap waits, the offer is almond milk and Riley's household records a tree-nut allergy.
        db.get(Substitution, sub["id"]).replacement_product_id = db.scalar(select(Product.id).where(Product.name == "Almond Milk 1L"))
        household = db.scalar(select(Household).join(User).where(User.email == "riley@trolleymate.demo"))
        household.members[0].dietary_profiles.append(
            DietaryProfile(restriction="tree_nuts", kind=RestrictionKind.allergy, severity=Severity.severe))
        db.commit()

    r = client.post(f"/api/substitutions/{sub['id']}/accept", headers=riley)
    assert r.status_code == 400 and "no longer passes" in r.json()["detail"]  # KAN-23 safety gate S10
    after = client.get(f"/api/baskets/{basket['id']}", headers=riley).json()
    assert item_in(after, item["id"])["product"]["id"] == item["product"]["id"]
    assert after["total"] == basket["total"]
    with SessionLocal() as db:
        assert db.get(Substitution, sub["id"]).status != "accepted"
    # Retrying is checked again, so it can never go through.
    assert client.post(f"/api/substitutions/{sub['id']}/accept", headers=riley).status_code == 400


def test_out_of_stock_item_is_flagged_and_removed_when_nothing_fits(client, riley):
    basket = build(client, riley)
    item = basket["items"][0]
    with SessionLocal() as db:
        bi = db.get(BasketItem, item["id"])
        for q in db.scalars(select(PriceQuote).where(PriceQuote.product_id == bi.product_id, PriceQuote.retailer_id == bi.retailer_id)):
            q.mark_unavailable("Retailer reports no stock")
        # Every alternative was already declined this session.
        session = db.get(ShoppingSession, basket["session_id"])
        session.rejected_swaps = [[bi.product_id, pid] for pid in db.scalars(select(Product.id))]
        db.commit()

    flagged = client.get(f"/api/baskets/{basket['id']}", headers=riley).json()
    assert item_in(flagged, item["id"])["flags"] == ["out_of_stock"]

    r = propose(client, riley, basket["id"], item["id"], "out_of_stock").json()
    assert r["substitution"]["status"] == "discarded" and r["substitution"]["facts"]["no_alternative"]
    assert item_in(r["basket"], item["id"]) is None
    assert f"{item['product']['name']} was removed — no suitable substitute was available." in r["basket"]["notifications"]
    assert r["basket"]["total"] == pytest.approx(basket["total"] - item["line_total"])


def test_cheaper_equivalent_is_cheaper_or_the_item_stays(client, riley):
    basket = build(client, riley)
    for item in basket["items"]:
        r = propose(client, riley, basket["id"], item["id"], "cheaper").json()
        sub = r["substitution"]
        if sub["status"] == "pending":
            assert sub["replacement_price"] < item["pack_price"] and sub["facts"]["saving"] > 0
        else:
            assert sub["trade_off"].startswith("No cheaper substitute")
            assert item_in(r["basket"], item["id"]) is not None


@pytest.mark.parametrize("reason, message", [
    ("out_of_stock", "is still in stock"),
    ("over_budget", "within budget"),
    ("failed_review", "has not failed a dietary review"),
])
def test_a_system_reason_must_actually_hold(client, riley, reason, message):
    """The client can't claim a system flag: those reasons let the system remove the item."""
    basket = build(client, riley)
    item = basket["items"][0]
    assert item["flags"] == []
    r = propose(client, riley, basket["id"], item["id"], reason)
    assert r.status_code == 400 and message in r.json()["detail"]
    with SessionLocal() as db:
        assert db.scalar(select(Substitution).where(Substitution.basket_item_id == item["id"])) is None
