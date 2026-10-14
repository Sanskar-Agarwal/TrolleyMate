"""PriceSource «interface» and its two adapters (class diagram, Pricing package).

Feature diagram: Price Data Freshness is XOR — Real-time (≤1 h, needs Partner API)
or Daily refresh (≤24 h, catalogue feed). Both adapters here simulate their feed
from `seed/catalogue.json` so the prototype runs offline.

TODO(pricing owner): replace `PartnerApiAdapter._fetch` with a real HTTP call to a
retailer/partner API, or a scraper of a public catalogue, behind the same interface.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.domain.basket_products import Product
from app.domain.pricing import Retailer

CATALOGUE_PATH = Path(__file__).resolve().parents[2] / "seed" / "catalogue.json"


@dataclass
class QuoteData:
    price: float
    on_special: bool
    captured_at: datetime


class PriceSource(Protocol):
    def quote_for(self, product: Product, retailer: Retailer) -> QuoteData | None: ...

    def last_refreshed(self) -> datetime: ...


@lru_cache
def _catalogue() -> dict:
    return json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))


def _jitter(*keys: str, spread: float = 0.06) -> float:
    """Deterministic ±spread noise so retailers differ but runs are reproducible."""
    digest = hashlib.sha256("|".join(keys).encode()).digest()
    return 1 + ((digest[0] / 255) * 2 - 1) * spread


def retailer_price(sku: str, category: str, base_price: float, retailer_name: str, salt: str = "") -> float:
    retailer = next(r for r in _catalogue()["retailers"] if r["name"] == retailer_name)
    mult = retailer["multipliers"].get(category, retailer["multipliers"]["default"])
    return round(base_price * mult * _jitter(sku, retailer_name, salt), 2)


def _product_entry(sku: str) -> dict | None:
    return next((p for p in _catalogue()["products"] if p["sku"] == sku), None)


class CatalogueFeedAdapter:
    """Daily catalogue feed (≤24 h freshness)."""

    def __init__(self) -> None:
        self._refreshed = datetime.now()

    def quote_for(self, product: Product, retailer: Retailer) -> QuoteData | None:
        return self._fetch(product, retailer)

    def _fetch(self, product: Product, retailer: Retailer) -> QuoteData | None:
        entry = _product_entry(product.sku)
        if entry is None or retailer.name in entry.get("unavailable_at", []):
            return None
        now = datetime.now()
        special = entry.get("special")
        if special and special["weekday"] == now.weekday():
            price = retailer_price(product.sku, product.category, special["price"], retailer.name, "special")
            return QuoteData(price=price, on_special=True, captured_at=now)
        price = retailer_price(product.sku, product.category, entry["base_price"], retailer.name, now.date().isoformat())
        return QuoteData(price=price, on_special=False, captured_at=now)

    def last_refreshed(self) -> datetime:
        return self._refreshed


class PartnerApiAdapter(CatalogueFeedAdapter):
    """Real-time partner API (≤1 h freshness). Simulated — see module TODO."""


def source_for(retailer: Retailer) -> PriceSource:
    return PartnerApiAdapter() if retailer.source == "partner_api" else CatalogueFeedAdapter()
