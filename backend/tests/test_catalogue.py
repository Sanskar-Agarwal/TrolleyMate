"""KAN-13 — Product and pricing data contract tests.

Verifies the acceptance criteria:
  - Catalogue metadata (schema_version, generated_at, data_provenance) is present.
  - Live / recorded / synthetic quotes are tagged correctly.
  - Stale quotes are detected by PriceQuote.is_stale().
  - Malformed product (PRO-MAL-BAR) is loaded and flagged data_complete=False.
  - Discontinued product (PRO-DIS-STEAK) generates no PriceQuote rows.
  - Product schema (product_schema.json) validates every catalogue product.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.domain.basket_products import Product
from app.domain.enums import QuoteSource, QuoteStatus
from app.domain.pricing import PriceQuote, Retailer
from app.seed import load_catalogue

SEED_DIR = Path(__file__).resolve().parent.parent / "app" / "seed"


# ---------------------------------------------------------------------------
# Catalogue metadata
# ---------------------------------------------------------------------------

def test_catalogue_has_schema_version():
    cat = load_catalogue()
    assert cat["schema_version"] == "1.0.0"


def test_catalogue_has_generated_at():
    cat = load_catalogue()
    assert "generated_at" in cat
    # Must be a valid ISO date string
    datetime.fromisoformat(cat["generated_at"])


def test_catalogue_has_data_provenance():
    cat = load_catalogue()
    assert cat["data_provenance"] in ("synthetic", "recorded", "live")


# ---------------------------------------------------------------------------
# Edge-case products in the raw catalogue
# ---------------------------------------------------------------------------

def test_malformed_product_has_null_nutrition():
    cat = load_catalogue()
    mal = next((p for p in cat["products"] if p["sku"] == "PRO-MAL-BAR"), None)
    assert mal is not None, "PRO-MAL-BAR missing from catalogue"
    assert mal["data_complete"] is False
    assert mal["nutrition"]["kcal"] is None


def test_discontinued_product_unavailable_everywhere():
    cat = load_catalogue()
    dis = next((p for p in cat["products"] if p["sku"] == "PRO-DIS-STEAK"), None)
    assert dis is not None, "PRO-DIS-STEAK missing from catalogue"
    retailer_names = {r["name"] for r in cat["retailers"]}
    assert retailer_names <= set(dis["unavailable_at"]), (
        "PRO-DIS-STEAK must be marked unavailable at every retailer"
    )


# ---------------------------------------------------------------------------
# Seeded DB: quote source_type tagging
# ---------------------------------------------------------------------------

def test_freshco_current_quotes_are_live(client):
    """FreshCo is a partner_api retailer — its current quotes should be tagged 'live'."""
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        freshco = db.scalar(select(Retailer).where(Retailer.name == "FreshCo"))
        assert freshco is not None
        quotes = db.scalars(
            select(PriceQuote)
            .where(PriceQuote.retailer_id == freshco.id)
            .where(PriceQuote.source_type == QuoteSource.live)
        ).all()
    assert len(quotes) > 0, "Expected live-tagged quotes for FreshCo"


def test_catalogue_retailer_current_quotes_are_synthetic(client):
    """GreenGrocer Express is a catalogue retailer — its current quotes should be 'synthetic'."""
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        gg = db.scalar(select(Retailer).where(Retailer.name == "GreenGrocer Express"))
        quotes = db.scalars(
            select(PriceQuote)
            .where(PriceQuote.retailer_id == gg.id)
            .where(PriceQuote.source_type == QuoteSource.synthetic)
        ).all()
    assert len(quotes) > 0, "Expected synthetic-tagged quotes for GreenGrocer Express"


def test_history_quotes_are_recorded(client):
    """All historical (superseded) quotes should be tagged 'recorded'."""
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        recorded = db.scalars(
            select(PriceQuote)
            .where(PriceQuote.status == QuoteStatus.superseded)
            .where(PriceQuote.source_type != QuoteSource.recorded)
        ).all()
    assert recorded == [], (
        f"Found {len(recorded)} superseded quotes not tagged 'recorded'"
    )


# ---------------------------------------------------------------------------
# Seeded DB: stale detection
# ---------------------------------------------------------------------------

def test_freshco_quotes_are_stale(client):
    """FreshCo quotes are seeded 30 h old and should have status=stale."""
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        freshco = db.scalar(select(Retailer).where(Retailer.name == "FreshCo"))
        stale = db.scalars(
            select(PriceQuote)
            .where(PriceQuote.retailer_id == freshco.id)
            .where(PriceQuote.status == QuoteStatus.stale)
        ).all()
    assert len(stale) > 0, "Expected stale FreshCo quotes in seed data"


def test_is_stale_detects_old_quote():
    quote = PriceQuote(captured_at=datetime.now() - timedelta(hours=25))
    assert quote.is_stale(max_age_hours=24) is True


def test_is_stale_accepts_fresh_quote():
    quote = PriceQuote(captured_at=datetime.now() - timedelta(hours=1))
    assert quote.is_stale(max_age_hours=24) is False


# ---------------------------------------------------------------------------
# Seeded DB: malformed product loaded with data_complete=False
# ---------------------------------------------------------------------------

def test_malformed_product_in_db(client):
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        mal = db.scalar(select(Product).where(Product.sku == "PRO-MAL-BAR"))
    assert mal is not None
    assert mal.data_complete is False
    assert mal.nutrition.get("kcal") is None


# ---------------------------------------------------------------------------
# Seeded DB: discontinued product has no price quotes
# ---------------------------------------------------------------------------

def test_discontinued_product_has_no_quotes(client):
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        dis = db.scalar(select(Product).where(Product.sku == "PRO-DIS-STEAK"))
        assert dis is not None
        quotes = db.scalars(
            select(PriceQuote).where(PriceQuote.product_id == dis.id)
        ).all()
    assert quotes == [], "Discontinued product should have no PriceQuote rows"


# ---------------------------------------------------------------------------
# JSON Schema validates catalogue
# ---------------------------------------------------------------------------

def test_product_schema_validates_all_products():
    """Every product in catalogue.json must satisfy product_schema.json."""
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")

    schema = json.loads((SEED_DIR / "product_schema.json").read_text())
    cat = load_catalogue()
    product_schema = schema["$defs"]["product"]
    for product in cat["products"]:
        errors = list(jsonschema.Draft202012Validator(product_schema).iter_errors(product))
        assert errors == [], (
            f"Product {product.get('sku')} failed schema validation: "
            + "; ".join(e.message for e in errors)
        )
