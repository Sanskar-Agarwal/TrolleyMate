"""KAN-14 — Multi-retailer ingestion and unit normalisation evidence tests.

Covers the acceptance criteria evidence items:
  - Adapter runs: CatalogueFeedAdapter and PartnerApiAdapter called directly
  - Unit tests: normalise() with valid and invalid inputs
  - Missing-field tests: null/zero price, unknown unit, SKU not in catalogue
  - Freshness tests: stale quote triggers refresh via MarketAnalystAgent
  - Quote-history tests: refresh supersedes old quote, never overwrites
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import select

from app.domain.basket_products import Product
from app.domain.enums import QuoteStatus
from app.domain.pricing import PriceQuote, Retailer
from app.services.pricing.normalisation import UnitPrice, normalise
from app.services.pricing.price_sources import (
    CatalogueFeedAdapter,
    PartnerApiAdapter,
    QuoteData,
    source_for,
)

# ---------------------------------------------------------------------------
# Helpers — simple namespaces satisfy the adapter's duck-typed interface
# ---------------------------------------------------------------------------

def _product(sku="PRO-CHB-500", category="protein", pack_size=500.0, unit="g"):
    """Minimal duck-typed product for adapter tests (no DB session required)."""
    return SimpleNamespace(id=None, sku=sku, name="Test product", category=category,
                           pack_size=pack_size, unit=unit, nutrition={}, servings=4)


def _retailer(name="GreenGrocer Express", source="catalogue"):
    return SimpleNamespace(id=None, name=name, source=source)


# ---------------------------------------------------------------------------
# Adapter run tests
# ---------------------------------------------------------------------------

def test_catalogue_adapter_returns_quote():
    """CatalogueFeedAdapter.quote_for returns a QuoteData with a positive price."""
    adapter = CatalogueFeedAdapter()
    result = adapter.quote_for(_product(), _retailer())
    assert isinstance(result, QuoteData)
    assert result.price > 0
    assert isinstance(result.captured_at, datetime)


def test_partner_api_adapter_returns_quote():
    """PartnerApiAdapter.quote_for returns a QuoteData (simulated live feed)."""
    adapter = PartnerApiAdapter()
    result = adapter.quote_for(_product(), _retailer("FreshCo", "partner_api"))
    assert isinstance(result, QuoteData)
    assert result.price > 0


def test_source_for_routes_catalogue_retailer():
    adapter = source_for(_retailer("GreenGrocer Express", "catalogue"))
    assert isinstance(adapter, CatalogueFeedAdapter)
    assert not isinstance(adapter, PartnerApiAdapter)


def test_source_for_routes_partner_api_retailer():
    adapter = source_for(_retailer("FreshCo", "partner_api"))
    assert isinstance(adapter, PartnerApiAdapter)


def test_adapter_run_is_reproducible():
    """Deterministic jitter means two calls with the same inputs return the same price."""
    adapter = CatalogueFeedAdapter()
    product = _product()
    retailer = _retailer()
    r1 = adapter.quote_for(product, retailer)
    r2 = adapter.quote_for(product, retailer)
    assert r1 is not None and r2 is not None
    assert r1.price == r2.price


# ---------------------------------------------------------------------------
# Missing / incompatible field tests
# ---------------------------------------------------------------------------

def test_normalise_returns_none_for_unknown_unit():
    """Units not in _TO_BASE (e.g. oz) must return None — caller must flag the product."""
    assert normalise(5.0, 100, "oz") is None


def test_normalise_returns_none_for_zero_price():
    assert normalise(0, 500, "g") is None


def test_normalise_returns_none_for_negative_price():
    assert normalise(-1.5, 500, "g") is None


def test_normalise_returns_none_for_zero_pack_size():
    assert normalise(5.0, 0, "g") is None


def test_normalise_returns_none_for_none_values():
    assert normalise(None, 500, "g") is None
    assert normalise(5.0, None, "g") is None


def test_adapter_unknown_sku_returns_none():
    """A product SKU not present in catalogue.json must return None without raising."""
    result = CatalogueFeedAdapter().quote_for(_product(sku="DOES-NOT-EXIST"), _retailer())
    assert result is None


def test_adapter_unavailable_at_retailer_returns_none():
    """PRO-LMB-500 is marked unavailable_at ValueMart."""
    result = CatalogueFeedAdapter().quote_for(_product(sku="PRO-LMB-500"), _retailer("ValueMart"))
    assert result is None


# ---------------------------------------------------------------------------
# Unit normalisation correctness
# ---------------------------------------------------------------------------

def test_normalise_grams():
    result = normalise(4.50, 1000, "g")
    assert result == UnitPrice(value=0.45, basis="100g")
    assert result.label() == "$0.45 / 100 g"


def test_normalise_kilograms():
    result = normalise(4.50, 1, "kg")
    assert result is not None
    assert result.basis == "100g"
    assert abs(result.value - 0.45) < 0.001


def test_normalise_millilitres():
    result = normalise(5.05, 2000, "ml")
    assert result is not None
    assert abs(result.value - 0.253) < 0.001
    assert result.basis == "100ml"


def test_normalise_litres():
    result = normalise(2.00, 1, "l")
    assert result is not None
    assert result.basis == "100ml"
    assert abs(result.value - 0.20) < 0.001


def test_normalise_each():
    result = normalise(6.20, 12, "each")
    assert result is not None
    assert result.basis == "each"
    assert result.label() == f"${result.value:.2f} / each"


# ---------------------------------------------------------------------------
# Freshness and quote-history tests (require seeded DB)
# ---------------------------------------------------------------------------

def test_stale_quote_is_superseded_on_refresh(client):
    """Refreshing a stale FreshCo quote creates a new row and supersedes the old one."""
    from app.agents.context import AgentContext
    from app.agents.market_analyst import MarketAnalystAgent
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        freshco = db.scalar(select(Retailer).where(Retailer.name == "FreshCo"))
        stale_quote = db.scalar(
            select(PriceQuote)
            .where(PriceQuote.retailer_id == freshco.id, PriceQuote.status == QuoteStatus.stale)
            .limit(1)
        )
        assert stale_quote is not None, "Seed should have stale FreshCo quotes"
        product = db.get(Product, stale_quote.product_id)

        old_id = stale_quote.id
        ctx = AgentContext(db=db, llm=None)
        analyst = MarketAnalystAgent(ctx)
        new_quote = analyst.current_quote(product, freshco, refresh=True)
        db.flush()

        assert new_quote is not None
        assert new_quote.id != old_id
        assert new_quote.status == QuoteStatus.fresh

        db.refresh(stale_quote)
        assert stale_quote.status == QuoteStatus.superseded
        assert stale_quote.superseded_by_id == new_quote.id


def test_refresh_does_not_overwrite_old_quote(client):
    """After refresh, the old quote row still exists in the DB (history retained)."""
    from app.agents.context import AgentContext
    from app.agents.market_analyst import MarketAnalystAgent
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        freshco = db.scalar(select(Retailer).where(Retailer.name == "FreshCo"))
        stale = db.scalar(
            select(PriceQuote)
            .where(PriceQuote.retailer_id == freshco.id, PriceQuote.status == QuoteStatus.stale)
            .limit(1)
        )
        product = db.get(Product, stale.product_id)
        old_id = stale.id
        old_price = stale.price

        ctx = AgentContext(db=db, llm=None)
        analyst = MarketAnalystAgent(ctx)
        analyst.current_quote(product, freshco, refresh=True)
        db.flush()

        old_row = db.get(PriceQuote, old_id)
        assert old_row is not None
        assert old_row.price == old_price  # value unchanged


def test_unavailable_product_refresh_marks_quote_unavailable(client):
    """If the adapter returns None during refresh, the quote is marked unavailable."""
    from app.agents.context import AgentContext
    from app.agents.market_analyst import MarketAnalystAgent
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        freshco = db.scalar(select(Retailer).where(Retailer.name == "FreshCo"))
        stale = db.scalar(
            select(PriceQuote)
            .where(PriceQuote.retailer_id == freshco.id, PriceQuote.status == QuoteStatus.stale)
            .limit(1)
        )
        ghost = SimpleNamespace(id=stale.product_id, sku="DOES-NOT-EXIST-IN-FEED",
                                pack_size=500.0, unit="g", category="protein")

        ctx = AgentContext(db=db, llm=None)
        analyst = MarketAnalystAgent(ctx)
        result = analyst._refresh(stale, ghost, freshco)

        assert result is None
        db.flush()
        assert stale.status == QuoteStatus.unavailable


def test_superseded_quote_retains_source_type(client):
    """Superseding a quote at runtime must not overwrite its source_type — the field records
    how the price was obtained (live, synthetic, recorded), which is historical fact.
    test_history_quotes_are_recorded covers seed data; this covers the runtime path."""
    from app.agents.context import AgentContext
    from app.agents.market_analyst import MarketAnalystAgent
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        freshco = db.scalar(select(Retailer).where(Retailer.name == "FreshCo"))
        stale = db.scalar(
            select(PriceQuote)
            .where(PriceQuote.retailer_id == freshco.id, PriceQuote.status == QuoteStatus.stale)
            .limit(1)
        )
        original_source = stale.source_type
        product = db.get(Product, stale.product_id)
        old_id = stale.id

        ctx = AgentContext(db=db, llm=None)
        analyst = MarketAnalystAgent(ctx)
        analyst.current_quote(product, freshco, refresh=True)
        db.flush()

        old_row = db.get(PriceQuote, old_id)
        assert old_row.status == QuoteStatus.superseded
        assert old_row.source_type == original_source  # "live" for FreshCo; must not be rewritten
