"""P04 (1.2.6): cautious buy-timing advice. Timestamped history gives an expected saving and a wait;
the advice abstains for insufficient history, daily staples and perishables that wouldn't keep; it never
changes the basket; and demo or synthetic history is labelled, never presented as a retailer forecast."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select

from app.core.db import SessionLocal
from app.domain import Basket, BasketItem, PriceQuote
from app.domain.enums import QuoteSource
from app.services import buy_timing
from tests.test_basket_flow import confirmed_session

NOW = datetime(2026, 10, 26, 12, 0)  # a Monday
WEDNESDAY = 2


def build(client, headers) -> dict:
    sid = confirmed_session(client, headers, "$80 for the week, two meals a day for myself")
    return client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=headers).json()["basket"]


def observed(monkeypatch):
    """A deployment whose history is real recorded data."""
    monkeypatch.setattr(buy_timing, "get_settings", lambda: SimpleNamespace(demo_price_history=False))


def set_history(db, item: BasketItem, weeks: int, *, special_weeks: int | None = None, source=QuoteSource.recorded,
                regular=5.0, special=3.0) -> None:
    """`weeks` weeks of Monday prices at the item's store, discounted on Wednesday in the most recent
    `special_weeks` of them (default: every week). The item costs $5.00 a pack, two packs."""
    db.execute(delete(PriceQuote).where(PriceQuote.product_id == item.product_id, PriceQuote.retailer_id == item.retailer_id))
    special_weeks = weeks if special_weeks is None else special_weeks
    for w in range(weeks, 0, -1):
        monday = datetime.combine((NOW - timedelta(weeks=w)).date(), datetime.min.time())
        db.add(PriceQuote(product_id=item.product_id, retailer_id=item.retailer_id, price=regular,
                          captured_at=monday + timedelta(hours=8), source_type=source))
        if w <= special_weeks:
            db.add(PriceQuote(product_id=item.product_id, retailer_id=item.retailer_id, price=special, on_special=True,
                              captured_at=monday + timedelta(days=WEDNESDAY, hours=7), source_type=source))
    item.pack_price, item.quantity = regular, 2
    product = item.product
    product.tags = [t for t in product.tags if t != "daily"]
    product.perishable, product.shelf_life_days = False, 30
    db.flush()


def advice_for(db, basket_id: int, item_id: int) -> dict:
    basket = db.get(Basket, basket_id)
    return next(a for a in buy_timing.advise(db, basket, now=NOW) if a["item_id"] == item_id)


@pytest.fixture()
def basket_item(client, riley):
    b = build(client, riley)
    return b["id"], b["items"][0]["id"]


# --- History sufficiency ---------------------------------------------------------------------------

def test_enough_history_states_the_saving_and_the_wait(monkeypatch, basket_item):
    observed(monkeypatch)
    basket_id, item_id = basket_item
    with SessionLocal() as db:
        item = db.get(BasketItem, item_id)
        set_history(db, item, 6)
        a = advice_for(db, basket_id, item_id)
    assert a["action"] == "wait"
    assert a["wait_days"] == 2 and a["wait_until"] == "2026-10-28" and a["pattern_day"] == "Wednesday"
    assert a["expected_price"] == 3.0 and a["expected_saving"] == 4.0  # ($5 − $3) × 2 packs
    assert a["confidence"] == 1.0
    h = a["history"]
    assert h["weeks"] == 6 and h["quotes"] == 12 and not h["demo"]
    assert h["from"] == "2026-09-14T08:00:00" and h["to"] == "2026-10-21T07:00:00"
    assert "should save about $4.00" in a["reason"] and "demo" not in a["reason"].lower()


@pytest.mark.parametrize("weeks", [0, 1, 5])
def test_too_little_history_abstains(monkeypatch, basket_item, weeks):
    observed(monkeypatch)
    basket_id, item_id = basket_item
    with SessionLocal() as db:
        set_history(db, db.get(BasketItem, item_id), weeks)
        a = advice_for(db, basket_id, item_id)
    assert a["action"] == "none" and "expected_saving" not in a and "wait_days" not in a
    assert f"({weeks} of 6 weeks needed)" in a["reason"]


def test_history_older_than_the_window_does_not_count(monkeypatch, basket_item):
    observed(monkeypatch)
    basket_id, item_id = basket_item
    with SessionLocal() as db:
        item = db.get(BasketItem, item_id)
        set_history(db, item, 6)
        # Shift everything back 3 weeks: only 5 of the 6 weeks fall inside the 8-week window.
        for q in db.scalars(select(PriceQuote).where(PriceQuote.product_id == item.product_id, PriceQuote.retailer_id == item.retailer_id)):
            q.captured_at -= timedelta(weeks=3)
        db.flush()
        a = advice_for(db, basket_id, item_id)
    assert a["action"] == "none"


def test_an_irregular_discount_is_not_a_pattern(monkeypatch, basket_item):
    observed(monkeypatch)
    basket_id, item_id = basket_item
    with SessionLocal() as db:
        set_history(db, db.get(BasketItem, item_id), 8, special_weeks=4)  # 50% of weeks < 75%
        a = advice_for(db, basket_id, item_id)
    assert a["action"] == "buy_now" and "irregular" in a["reason"] and "expected_saving" not in a


# --- Perishable and daily-staple exclusion -----------------------------------------------------------

def test_a_perishable_that_would_not_keep_is_left_out(monkeypatch, basket_item):
    observed(monkeypatch)
    basket_id, item_id = basket_item
    with SessionLocal() as db:
        item = db.get(BasketItem, item_id)
        set_history(db, item, 8)
        item.product.perishable, item.product.shelf_life_days = True, 1  # the wait is 2 days
        a = advice_for(db, basket_id, item_id)
    assert a["action"] == "skip" and "Perishable" in a["reason"]
    assert "wait_days" not in a and "expected_saving" not in a


def test_a_perishable_that_keeps_through_the_wait_also_abstains(monkeypatch, basket_item):
    observed(monkeypatch)
    basket_id, item_id = basket_item
    with SessionLocal() as db:
        item = db.get(BasketItem, item_id)
        set_history(db, item, 8)
        item.product.perishable, item.product.shelf_life_days = True, 5
        a = advice_for(db, basket_id, item_id)
    assert a["action"] == "skip" and "wait_days" not in a


def test_a_daily_staple_is_left_out_even_with_a_pattern(monkeypatch, basket_item):
    observed(monkeypatch)
    basket_id, item_id = basket_item
    with SessionLocal() as db:
        item = db.get(BasketItem, item_id)
        set_history(db, item, 8)
        item.product.tags = [*item.product.tags, "daily"]
        a = advice_for(db, basket_id, item_id)
    assert a["action"] == "skip" and "day-to-day" in a["reason"] and "history" not in a


# --- Demo / synthetic history ------------------------------------------------------------------------

def test_demo_history_is_labelled_and_not_a_forecast(basket_item):
    basket_id, item_id = basket_item  # default settings: the seeded history is demo data
    with SessionLocal() as db:
        set_history(db, db.get(BasketItem, item_id), 8)
        a = advice_for(db, basket_id, item_id)
    assert a["action"] == "wait" and a["history"]["demo"]
    assert a["reason"].startswith("In the demo price history")
    assert "if that pattern held" in a["reason"] and buy_timing.DEMO_NOTE in a["reason"]
    assert "should save" not in a["reason"]


def test_synthetic_quotes_make_history_demo_even_when_the_deployment_is_not(monkeypatch, basket_item):
    observed(monkeypatch)
    basket_id, item_id = basket_item
    with SessionLocal() as db:
        set_history(db, db.get(BasketItem, item_id), 8, source=QuoteSource.synthetic)
        a = advice_for(db, basket_id, item_id)
    assert a["history"]["demo"] and "if that pattern held" in a["reason"]


def test_the_api_flags_the_seeded_history_as_demo(client, riley):
    b = build(client, riley)
    r = client.get(f"/api/baskets/{b['id']}/buy-timing", headers=riley).json()
    assert r["demo_history"] and r["history_note"] == buy_timing.DEMO_NOTE
    with_history = [a for a in r["advice"] if "history" in a]
    assert with_history and all(a["history"]["demo"] for a in with_history)
    assert not any("should save" in a["reason"] for a in r["advice"])


# --- Advice never changes the basket -----------------------------------------------------------------

def test_advice_does_not_change_the_basket(client, riley):
    b = build(client, riley)
    with SessionLocal() as db:
        # Make sure at least one item gets "wait" advice, the case most tempting to act on.
        set_history(db, db.get(BasketItem, b["items"][0]["id"]), 8)
        db.commit()
        quotes_before = db.scalar(select(func.count()).select_from(PriceQuote))
    before = client.get(f"/api/baskets/{b['id']}", headers=riley).json()

    for _ in range(2):
        r = client.get(f"/api/baskets/{b['id']}/buy-timing", headers=riley)
        assert r.status_code == 200
    assert any(a["action"] == "wait" for a in r.json()["advice"])

    after = client.get(f"/api/baskets/{b['id']}", headers=riley).json()
    assert after == before
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PriceQuote)) == quotes_before
        basket = db.get(Basket, b["id"])
        assert basket.status == before["status"] and basket.total == before["total"]
