"""P05 (1.2.4–1.2.6): regression matrix of negotiation, substitution and buy-timing failure paths,
run through the integrated release's API. Each scenario states its expected outcome and records what
was observed, so the run doubles as evidence:

    P05_REPORT=../docs/evidence/p05-failure-paths.md python -m pytest tests/test_failure_paths.py

writes the expected-versus-observed table (see docs/P05_REGRESSION.md for defects and retests).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.domain import Basket, BasketItem, DietaryProfile, Household, PriceQuote, Product, ShoppingRequest, Substitution, User
from app.domain.enums import RestrictionKind, Severity
from tests.test_basket_flow import confirmed_session
from tests.test_buy_timing import advice_for, set_history
from tests.test_negotiation import TWO_DAYS, _active, _baskets
from tests.test_negotiation import analyse as analyse_fixture
from tests.test_substitution import ALEX_WEEK, UNSAFE_FOR_ALEX, decline_until_exhausted, first_pending, item_in, propose

WEEK = "$80 for the week, two meals a day for myself"
INFEASIBLE_WEEK = "$8 for the week, three meals a day for myself"
TIMEOUT = SimpleNamespace(x=None, status=1, fun=None)


@dataclass
class Scenario:
    id: str
    requirement: str
    title: str
    expected: dict
    run: Callable[[SimpleNamespace], dict]


RESULTS: list[tuple[Scenario, dict | str]] = []


# --- Helpers -------------------------------------------------------------------------------------

def basket(t, headers=None, text=WEEK, goal="balanced") -> dict:
    headers = headers or t.riley
    sid = confirmed_session(t.client, headers, text)
    r = t.client.post(f"/api/sessions/{sid}/basket", json={"goal": goal}, headers=headers).json()
    assert r["status"] == "ok", r
    return r["basket"]


def get(t, b, headers=None) -> dict:
    return t.client.get(f"/api/baskets/{b['id']}", headers=headers or t.riley).json()


def set_budget(b: dict, budget: float) -> None:
    with SessionLocal() as db:
        db.get(Basket, b["id"]).budget = budget
        db.commit()


def out_of_stock(item: dict) -> None:
    with SessionLocal() as db:
        bi = db.get(BasketItem, item["id"])
        for q in db.scalars(select(PriceQuote).where(PriceQuote.product_id == bi.product_id, PriceQuote.retailer_id == bi.retailer_id)):
            q.mark_unavailable("Retailer reports no stock")
        db.commit()


def decline_everything(b: dict, item: dict) -> None:
    with SessionLocal() as db:
        from app.domain import ShoppingSession

        bi = db.get(BasketItem, item["id"])
        db.get(ShoppingSession, b["session_id"]).rejected_swaps = [[bi.product_id, pid] for pid in db.scalars(select(Product.id))]
        db.commit()


def infeasible(t, headers=None) -> tuple[int, dict]:
    headers = headers or t.riley
    sid = confirmed_session(t.client, headers, INFEASIBLE_WEEK)
    r = t.client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=headers).json()
    assert r["status"] == "infeasible", r
    return sid, r["negotiation"]


def request_status(sid: int) -> str:
    with SessionLocal() as db:
        return db.scalar(select(ShoppingRequest).where(ShoppingRequest.session_id == sid)).status


def observed_history(t) -> None:
    t.monkeypatch.setattr("app.services.buy_timing.get_settings", lambda: SimpleNamespace(demo_price_history=False))


# --- Scenarios -----------------------------------------------------------------------------------

def over_budget_swap(t) -> dict:
    b = basket(t)
    set_budget(b, round(b["total"] - 0.5, 2))
    flagged = get(t, b)
    for item in flagged["items"]:
        r = propose(t.client, t.riley, b["id"], item["id"], "over_budget").json()
        sub = r["substitution"]
        if sub["status"] == "pending":
            others = sum(i["line_total"] for i in flagged["items"] if i["id"] != item["id"] and not i["withheld"])
            return {"flagged": "over_budget" in item["flags"], "swap": "offered",
                    "fits_budget": others + sub["replacement_price"] * item["quantity"] <= flagged["budget"] + 1e-6}
    return {"flagged": True, "swap": "none found", "fits_budget": None}


def over_budget_no_alternative(t) -> dict:
    b = basket(t)
    set_budget(b, 1.0)
    item = b["items"][0]
    r = propose(t.client, t.riley, b["id"], item["id"], "over_budget").json()
    return {"status": r["substitution"]["status"], "no_alternative": r["substitution"]["facts"].get("no_alternative"),
            "item_kept": item_in(r["basket"], item["id"]) is not None}


def out_of_stock_swap(t) -> dict:
    b = basket(t)
    for item in b["items"]:
        out_of_stock(item)
        flags = item_in(get(t, b), item["id"])["flags"]
        sub = propose(t.client, t.riley, b["id"], item["id"], "out_of_stock").json()["substitution"]
        if sub["status"] != "pending":
            continue
        r = t.client.post(f"/api/substitutions/{sub['id']}/accept", headers=t.riley).json()
        swapped = item_in(r["basket"], item["id"])
        return {"flagged": flags == ["out_of_stock"], "status": r["substitution"]["status"],
                "replaced": swapped["product"]["id"] == sub["replacement"]["id"], "flag_cleared": swapped["flags"] == []}
    return {"flagged": None, "status": "no swap for any item", "replaced": False, "flag_cleared": False}


def out_of_stock_no_alternative(t) -> dict:
    b = basket(t)
    item = b["items"][0]
    out_of_stock(item)
    decline_everything(b, item)
    r = propose(t.client, t.riley, b["id"], item["id"], "out_of_stock").json()
    notice = f"{item['product']['name']} was removed — no suitable substitute was available."
    return {"status": r["substitution"]["status"], "item_removed": item_in(r["basket"], item["id"]) is None,
            "notified": notice in r["basket"]["notifications"]}


def claimed_out_of_stock(t) -> dict:
    b = basket(t)
    r = propose(t.client, t.riley, b["id"], b["items"][0]["id"], "out_of_stock")
    return {"http": r.status_code, "item_kept": item_in(get(t, b), b["items"][0]["id"]) is not None}


def unsafe_candidates(t) -> dict:
    b = basket(t, t.alex, ALEX_WEEK)
    with SessionLocal() as db:
        item = db.get(BasketItem, b["items"][0]["id"])
        item.product_id = db.scalar(select(Product.id).where(Product.name == "Lactose Free Milk 2L"))
        db.commit()
    offered, last = decline_until_exhausted(t.client, t.alex, b["id"], b["items"][0]["id"])
    return {"unsafe_offered": sorted(UNSAFE_FOR_ALEX & set(offered)), "safe_offered": "Soy Milk 1L" in offered,
            "ends_with_no_alternative": bool(last["substitution"]["facts"].get("no_alternative"))}


def unsafe_on_accept(t) -> dict:
    b = basket(t)
    item, sub = first_pending(t.client, t.riley, b)
    with SessionLocal() as db:
        db.get(Substitution, sub["id"]).replacement_product_id = db.scalar(select(Product.id).where(Product.name == "Almond Milk 1L"))
        household = db.scalar(select(Household).join(User).where(User.email == "riley@trolleymate.demo"))
        household.members[0].dietary_profiles.append(
            DietaryProfile(restriction="tree_nuts", kind=RestrictionKind.allergy, severity=Severity.severe))
        db.commit()
    r = t.client.post(f"/api/substitutions/{sub['id']}/accept", headers=t.riley)
    after = get(t, b)
    return {"http": r.status_code,
            "original_kept": item_in(after, item["id"])["product"]["id"] == item["product"]["id"],
            "total_unchanged": after["total"] == b["total"]}


def declined_swap_remembered(t) -> dict:
    b = basket(t)
    item, sub = first_pending(t.client, t.riley, b)
    t.client.post(f"/api/substitutions/{sub['id']}/reject", headers=t.riley)
    again = propose(t.client, t.riley, b["id"], item["id"]).json()["substitution"]
    return {"original_kept": item_in(get(t, b), item["id"])["product"]["id"] == item["product"]["id"],
            "same_swap_again": again["replacement"] is not None and again["replacement"]["id"] == sub["replacement"]["id"]}


def declined_trade_off_cancel(t) -> dict:
    sid, _ = infeasible(t)
    r = t.client.post(f"/api/sessions/{sid}/negotiate/cancel", headers=t.riley).json()
    return {"status": r["status"], "constraint_version": _active(sid).version, "request": request_status(sid),
            "baskets": _baskets(sid)}


def rejected_choice_still_infeasible(t) -> dict:
    sid, _ = infeasible(t)
    r = t.client.post(f"/api/sessions/{sid}/negotiate", json={"budget": 9.0}, headers=t.riley).json()
    return {"status": r["status"], "fresh_options": bool(r.get("negotiation", {}).get("options")),
            "constraint_version": _active(sid).version, "budget_kept": _active(sid).payload["budget"]}


def restriction_not_negotiable(t) -> dict:
    sid, _ = infeasible(t, t.alex)
    before = _active(sid).payload.get("restrictions")
    r = t.client.post(f"/api/sessions/{sid}/negotiate", json={"budget": 500, "restrictions": []}, headers=t.alex)
    return {"http": r.status_code, "restrictions_unchanged": _active(sid).payload.get("restrictions") == before}


def build_timeout(t) -> dict:
    sid = confirmed_session(t.client, t.riley, WEEK)
    t.monkeypatch.setattr("app.optimisation.basket_optimiser.milp", lambda **_: TIMEOUT)
    r = t.client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=t.riley).json()
    t.monkeypatch.undo()
    retry = t.client.post(f"/api/sessions/{sid}/basket", json={"goal": "balanced"}, headers=t.riley).json()
    return {"status": r["status"], "reason": r.get("reason"), "negotiation_started": "negotiation" in r,
            "request": request_status(sid), "retry": retry["status"]}


def negotiation_search_timeout(t) -> dict:
    t.monkeypatch.setattr("app.optimisation.basket_optimiser.milp", lambda **_: TIMEOUT)
    info, _ = analyse_fixture(TWO_DAYS)
    return {"options": len(info["options"]), "blocked_roles": info["blocked_roles"], "flagged": info["timed_out"]}


def insufficient_history(t) -> dict:
    observed_history(t)
    b = basket(t)
    with SessionLocal() as db:
        set_history(db, db.get(BasketItem, b["items"][0]["id"]), 5)
        a = advice_for(db, b["id"], b["items"][0]["id"])
    return {"action": a["action"], "saving_stated": "expected_saving" in a}


def sufficient_history(t) -> dict:
    observed_history(t)
    b = basket(t)
    with SessionLocal() as db:
        set_history(db, db.get(BasketItem, b["items"][0]["id"]), 6)
        a = advice_for(db, b["id"], b["items"][0]["id"])
    return {"action": a["action"], "wait_days": a.get("wait_days"), "expected_saving": a.get("expected_saving")}


def perishable_excluded(t) -> dict:
    observed_history(t)
    b = basket(t)
    with SessionLocal() as db:
        item = db.get(BasketItem, b["items"][0]["id"])
        set_history(db, item, 8)
        item.product.perishable, item.product.shelf_life_days = True, 1
        a = advice_for(db, b["id"], b["items"][0]["id"])
    return {"action": a["action"], "wait_given": "wait_days" in a}


def demo_history_labelled(t) -> dict:
    b = basket(t)
    r = t.client.get(f"/api/baskets/{b['id']}/buy-timing", headers=t.riley).json()
    return {"demo_history": r["demo_history"], "forecast_wording": any("should save" in a["reason"] for a in r["advice"])}


def timing_leaves_basket(t) -> dict:
    b = basket(t)
    before = get(t, b)
    t.client.get(f"/api/baskets/{b['id']}/buy-timing", headers=t.riley)
    return {"basket_unchanged": get(t, b) == before}


SCENARIOS = [
    Scenario("FP-01", "1.2.5", "Over budget: a cheaper compliant swap that fits is offered",
             {"flagged": True, "swap": "offered", "fits_budget": True}, over_budget_swap),
    Scenario("FP-02", "1.2.5", "Over budget, no swap fits: reported, item kept",
             {"status": "discarded", "no_alternative": True, "item_kept": True}, over_budget_no_alternative),
    Scenario("FP-03", "1.2.5", "Out of stock: flagged, swap offered and applied on acceptance",
             {"flagged": True, "status": "accepted", "replaced": True, "flag_cleared": True}, out_of_stock_swap),
    Scenario("FP-04", "1.2.5", "Out of stock, no alternative: item removed and shopper notified",
             {"status": "discarded", "item_removed": True, "notified": True}, out_of_stock_no_alternative),
    Scenario("FP-05", "1.2.5", "Client claims out of stock for an in-stock item: refused",
             {"http": 400, "item_kept": True}, claimed_out_of_stock),
    Scenario("FP-06", "1.2.5", "Unsafe candidates (lactose, tree nuts, unconfirmed) never offered",
             {"unsafe_offered": [], "safe_offered": True, "ends_with_no_alternative": True}, unsafe_candidates),
    Scenario("FP-07", "1.2.5", "Swap became unsafe before acceptance: refused, original kept",
             {"http": 400, "original_kept": True, "total_unchanged": True}, unsafe_on_accept),
    Scenario("FP-08", "1.2.5", "Declined swap: original kept, not offered again this session",
             {"original_kept": True, "same_swap_again": False}, declined_swap_remembered),
    Scenario("FP-09", "1.2.4", "Declined trade-off (cancel): constraints and request unchanged",
             {"status": "cancelled", "constraint_version": 1, "request": "infeasible", "baskets": 0}, declined_trade_off_cancel),
    Scenario("FP-10", "1.2.4", "Chosen numbers still infeasible: fresh options, constraints unchanged",
             {"status": "infeasible", "fresh_options": True, "constraint_version": 1, "budget_kept": 8}, rejected_choice_still_infeasible),
    Scenario("FP-11", "1.2.4", "Restrictions can't be traded through negotiation",
             {"http": 422, "restrictions_unchanged": True}, restriction_not_negotiable),
    Scenario("FP-12", "1.2.4", "Build timeout: retry offered, no negotiation, request still confirmed",
             {"status": "retryable", "reason": "timeout", "negotiation_started": False, "request": "confirmed", "retry": "ok"},
             build_timeout),
    Scenario("FP-13", "1.2.4", "Timeout while searching trade-offs: no wrong option or blocked role",
             {"options": 0, "blocked_roles": [], "flagged": True}, negotiation_search_timeout),
    Scenario("FP-14", "1.2.6", "Insufficient history (5 of 6 weeks): abstains",
             {"action": "none", "saving_stated": False}, insufficient_history),
    Scenario("FP-15", "1.2.6", "Sufficient history (6 weeks): saving and wait stated",
             {"action": "wait", "wait_days": 2, "expected_saving": 4.0}, sufficient_history),
    Scenario("FP-16", "1.2.6", "Perishable that wouldn't keep: left out",
             {"action": "skip", "wait_given": False}, perishable_excluded),
    Scenario("FP-17", "1.2.6", "Seeded demo history labelled, never worded as a forecast",
             {"demo_history": True, "forecast_wording": False}, demo_history_labelled),
    Scenario("FP-18", "1.2.6", "Timing advice leaves the basket unchanged",
             {"basket_unchanged": True}, timing_leaves_basket),
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_failure_path(scenario: Scenario, client, riley, alex, monkeypatch):
    t = SimpleNamespace(client=client, riley=riley, alex=alex, monkeypatch=monkeypatch)
    try:
        observed = scenario.run(t)
    except Exception as exc:  # noqa: BLE001 — recorded as the observed result, then re-raised
        RESULTS.append((scenario, f"error: {type(exc).__name__}: {exc}"))
        raise
    RESULTS.append((scenario, observed))
    assert observed == scenario.expected


def _cell(value) -> str:
    return str(value).replace("|", "\\|")


@pytest.fixture(scope="module", autouse=True)
def report():
    yield
    path = os.environ.get("P05_REPORT")
    if not path or not RESULTS:
        return
    passed = sum(1 for s, o in RESULTS if o == s.expected)
    lines = [
        "# P05 failure-path regression results",
        "",
        f"Run {datetime.now():%Y-%m-%d %H:%M} against the integrated release · {passed}/{len(RESULTS)} passed · "
        "generated by `backend/tests/test_failure_paths.py`",
        "",
        "| ID | Req. | Scenario | Expected | Observed | Result |",
        "|---|---|---|---|---|---|",
    ]
    for s, observed in RESULTS:
        result = "PASS" if observed == s.expected else "FAIL"
        lines.append(f"| {s.id} | {s.requirement} | {s.title} | `{_cell(s.expected)}` | `{_cell(observed)}` | {result} |")
    Path(path).write_text("\n".join(lines) + "\n")

