"""KAN-15 — Named-baseline savings comparisons evidence tests.

Covers the acceptance criteria:
  - Named baseline: savings computed relative to a selected retailer
  - Dollar and percentage savings: hand-checked arithmetic
  - Split basket: cheapest-per-item option is included and correct
  - Incomplete data: incomplete options excluded from cheapest/insight
  - Zero baseline: no ZeroDivisionError when baseline retailer has no priced items
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.agents.market_analyst import MarketAnalystAgent

# ---------------------------------------------------------------------------
# Fake domain objects (no DB required)
# ---------------------------------------------------------------------------

def _retailer(id, name):
    return SimpleNamespace(id=id, name=name, source="catalogue")


def _product(id, name):
    return SimpleNamespace(id=id, name=name)


def _item(id, product_id, product_name, quantity, withheld=False):
    return SimpleNamespace(
        id=id, product_id=product_id, quantity=quantity, withheld=withheld,
        product=_product(product_id, product_name),
    )


def _basket(items):
    return SimpleNamespace(id=1, session_id=1, items=items)


def _quote(price, unit_price=None, unit_basis="each", on_special=False):
    return SimpleNamespace(price=price, unit_price=unit_price, unit_basis=unit_basis, on_special=on_special)


def _make_analyst(retailers, quote_map):
    """Build a MarketAnalystAgent with stubbed retailers and price lookups.

    quote_map: dict[(product_id, retailer_id)] → quote | None
    """
    ctx = MagicMock()
    analyst = MarketAnalystAgent(ctx)
    analyst._retailers = retailers
    analyst._latest_quotes = lambda product_ids: {
        k: v for k, v in quote_map.items() if k[0] in product_ids and v is not None
    }
    analyst._usable = lambda quote, product, retailer, refresh: quote_map.get((product.id, retailer.id))
    analyst.think = MagicMock(return_value=MagicMock(data="Switching saves money."))
    return analyst


# ---------------------------------------------------------------------------
# Shared fixtures
#
#   Two retailers:
#     R1 "GreenGrocer Express"  id=1
#     R2 "ValueMart"            id=2
#
#   Two basket items, hand-verified totals:
#     Item1 Oats 1kg     qty=2: R1=$3.00/unit → line $6.00 | R2=$2.00/unit → line $4.00
#     Item2 Olive Oil    qty=1: R1=$5.00       → line $5.00 | R2=$8.00      → line $8.00
#
#   Retailer totals:  R1=$11.00   R2=$12.00
#   Split total:      item1@R2($4.00) + item2@R1($5.00) = $9.00
# ---------------------------------------------------------------------------

R1 = _retailer(1, "GreenGrocer Express")
R2 = _retailer(2, "ValueMart")
RETAILERS = [R1, R2]

ITEMS = [
    _item(id=1, product_id=101, product_name="Oats 1kg",       quantity=2),
    _item(id=2, product_id=102, product_name="Olive Oil 500ml", quantity=1),
]

QUOTE_MAP = {
    (101, 1): _quote(3.00),
    (101, 2): _quote(2.00),
    (102, 1): _quote(5.00),
    (102, 2): _quote(8.00),
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_named_baseline_selects_correct_retailer():
    """Passing baseline_id=R2.id reports savings relative to ValueMart, not GreenGrocer Express."""
    analyst = _make_analyst(RETAILERS, QUOTE_MAP)
    result = analyst.compare(_basket(ITEMS), baseline_id=R2.id)

    assert result["baseline"]["id"] == R2.id
    assert result["baseline"]["name"] == "ValueMart"
    assert result["baseline"]["total"] == 12.00

    # R1 total=$11.00 vs baseline $12.00 → saving=$1.00, 8.3 %
    r1_opt = next(o for o in result["options"] if o["retailer_id"] == R1.id)
    assert r1_opt["saving"] == 1.00
    assert r1_opt["saving_pct"] == 8.3


def test_dollar_and_percentage_savings_are_correct():
    """Hand-checked arithmetic: R1 baseline=$11.00; R2=$12.00 costs $1.00 more (−9.1 %)."""
    analyst = _make_analyst(RETAILERS, QUOTE_MAP)
    result = analyst.compare(_basket(ITEMS), baseline_id=R1.id)

    assert result["baseline"]["total"] == 11.00

    r1_opt = next(o for o in result["options"] if o["retailer_id"] == R1.id)
    assert r1_opt["total"] == 11.00
    assert r1_opt["saving"] == 0.00
    assert r1_opt["saving_pct"] == 0.0

    r2_opt = next(o for o in result["options"] if o["retailer_id"] == R2.id)
    assert r2_opt["total"] == 12.00
    # saving = 11.00 - 12.00 = -1.00 (R2 costs more than baseline)
    assert r2_opt["saving"] == -1.00
    assert r2_opt["saving_pct"] == -9.1


def test_split_basket_option_is_included():
    """Split-basket option picks cheapest per item; total=$9.00, saves $2.00 (18.2 %) vs R1."""
    analyst = _make_analyst(RETAILERS, QUOTE_MAP)
    result = analyst.compare(_basket(ITEMS), baseline_id=R1.id)

    split = next((o for o in result["options"] if o["is_split"]), None)
    assert split is not None, "Split basket option missing from results"

    # item1 cheapest at R2 ($4.00) + item2 cheapest at R1 ($5.00) = $9.00
    assert split["total"] == 9.00
    assert split["saving"] == 2.00
    assert split["saving_pct"] == 18.2

    # Split must not exceed any single-retailer option
    single_totals = [o["total"] for o in result["options"] if not o["is_split"]]
    assert split["total"] <= min(single_totals)


def test_incomplete_option_excluded_from_cheapest():
    """When R2 has no price for item2, its option is marked incomplete and excluded from cheapest."""
    incomplete_map = {
        (101, 1): _quote(3.00),
        (101, 2): _quote(2.00),
        (102, 1): _quote(5.00),
        # (102, 2) absent — R2 cannot price Olive Oil
    }
    analyst = _make_analyst(RETAILERS, incomplete_map)
    result = analyst.compare(_basket(ITEMS), baseline_id=R1.id)

    r2_opt = next(o for o in result["options"] if o["retailer_id"] == R2.id)
    assert r2_opt["complete"] is False
    assert "Olive Oil 500ml" in r2_opt["unpriced"]

    # Cheapest must only come from complete options — not R2
    assert result["cheapest"] is not None, "At least one complete option should exist"
    assert result["cheapest"]["retailer_id"] != R2.id


def test_zero_baseline_does_not_divide():
    """When baseline retailer has no priced items (base_total=0), saving_pct is 0.0, no exception."""
    # R1 (baseline) has no prices; R2 has both
    zero_baseline_map = {
        (101, 2): _quote(2.00),
        (102, 2): _quote(8.00),
    }
    analyst = _make_analyst(RETAILERS, zero_baseline_map)

    # Must not raise ZeroDivisionError
    result = analyst.compare(_basket(ITEMS), baseline_id=R1.id)

    assert result["baseline"]["total"] == 0.00
    for opt in result["options"]:
        assert opt["saving_pct"] == 0.0
