"""1.2.7: real price feeds — the partner HTTP adapter and the recorded-price importer."""

import json
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.domain import PriceQuote, Product, Retailer
from app.domain.enums import QuoteSource, QuoteStatus
from app.services.pricing.importer import import_quotes, read_rows
from app.services.pricing.price_sources import PartnerApiAdapter


@pytest.fixture()
def partner(monkeypatch):
    monkeypatch.setattr(get_settings(), "partner_api_url", "http://partner.test")
    return monkeypatch


def _product_and_retailer():
    with SessionLocal() as db:
        product = db.scalar(select(Product).where(Product.sku == "PRO-CHB-500"))
        retailer = db.scalar(select(Retailer).where(Retailer.name == "FreshCo"))
        db.expunge_all()
    return product, retailer


def test_partner_feed_quotes_are_live(client, partner):
    seen = {}

    def fake_get(url, params, headers, timeout):
        seen.update(params)
        return httpx.Response(200, json={"price": 6.1, "on_special": True, "captured_at": "2026-10-27T09:00:00"})

    partner.setattr(httpx, "get", fake_get)
    product, retailer = _product_and_retailer()
    quote = PartnerApiAdapter().quote_for(product, retailer)
    assert seen == {"retailer": "FreshCo", "sku": "PRO-CHB-500"}
    assert (quote.price, quote.on_special, quote.source) == (6.1, True, QuoteSource.live)


def test_partner_404_means_not_stocked(client, partner):
    partner.setattr(httpx, "get", lambda *a, **k: httpx.Response(404))
    assert PartnerApiAdapter().quote_for(*_product_and_retailer()) is None


@pytest.mark.parametrize("response", [httpx.Response(500), httpx.Response(200, json={"price": "n/a"}), httpx.Response(200, json={})])
def test_partner_failure_falls_back_to_a_labelled_simulated_price(client, partner, response):
    partner.setattr(httpx, "get", lambda *a, **k: response)
    quote = PartnerApiAdapter().quote_for(*_product_and_retailer())
    assert quote is not None and quote.source == QuoteSource.synthetic


def test_without_a_url_partner_prices_are_labelled_synthetic(client):
    assert PartnerApiAdapter().quote_for(*_product_and_retailer()).source == QuoteSource.synthetic


def test_importer_records_history_and_reports_bad_rows(client, tmp_path):
    now = datetime.now().replace(microsecond=0)
    rows = [
        {"retailer": "ValueMart", "sku": "PRO-CHB-500", "price": "5.55", "on_special": "yes", "captured_at": now.isoformat()},
        {"retailer": "ValueMart", "sku": "PRO-CHB-500", "price": "9.99", "captured_at": (now - timedelta(days=30)).isoformat()},
        {"retailer": "Nowhere", "sku": "PRO-CHB-500", "price": "1"},
        {"retailer": "ValueMart", "sku": "NOPE", "price": "1"},
        {"retailer": "ValueMart", "sku": "PRO-CHB-500", "price": "-2"},
    ]
    path = tmp_path / "prices.json"
    path.write_text(json.dumps(rows))
    with SessionLocal() as db:
        report = import_quotes(db, read_rows(path))
        db.commit()
        product = db.scalar(select(Product).where(Product.sku == "PRO-CHB-500"))
        retailer = db.scalar(select(Retailer).where(Retailer.name == "ValueMart"))
        current = db.scalars(select(PriceQuote).where(
            PriceQuote.product_id == product.id, PriceQuote.retailer_id == retailer.id,
            PriceQuote.status != QuoteStatus.superseded)).all()
    assert (report.imported, report.became_current, len(report.rejected)) == (2, 1, 3)
    assert [(q.price, q.on_special, q.source_type) for q in current] == [(5.55, True, QuoteSource.recorded)]


def test_importer_reads_csv(tmp_path):
    path = tmp_path / "prices.csv"
    path.write_text("retailer,sku,price\nValueMart,PRO-CHB-500,5.10\n", encoding="utf-8")
    assert read_rows(path) == [{"retailer": "ValueMart", "sku": "PRO-CHB-500", "price": "5.10"}]
