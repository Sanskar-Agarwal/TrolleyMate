"""PriceSource «interface» and its two adapters (class diagram, Pricing package).

Feature diagram: Price Data Freshness is XOR — Real-time (≤1 h, needs Partner API)
or Daily refresh (≤24 h, catalogue feed). The catalogue feed is simulated from
`seed/catalogue.json`. The partner adapter calls PARTNER_API_URL when it's set and falls
back to the simulated feed otherwise; every quote says where it came from (`source`).
Recorded real prices can also be loaded from a file: `python -m app.services.pricing.importer`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.domain.basket_products import Product
from app.domain.enums import QuoteSource
from app.domain.pricing import Retailer

CATALOGUE_PATH = Path(__file__).resolve().parents[2] / "seed" / "catalogue.json"


log = logging.getLogger(__name__)


@dataclass
class QuoteData:
    price: float
    on_special: bool
    captured_at: datetime
    source: str = QuoteSource.synthetic


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
        special = entry.get("specials", {}).get(retailer.name)
        if special and now.weekday() in special.get("weekdays", [2]):
            price = retailer_price(product.sku, product.category, special["price"], retailer.name, "special")
            return QuoteData(price=price, on_special=True, captured_at=now)
        price = retailer_price(product.sku, product.category, entry["base_price"], retailer.name, now.date().isoformat())
        return QuoteData(price=price, on_special=False, captured_at=now)

    def last_refreshed(self) -> datetime:
        return self._refreshed


class PartnerApiAdapter(CatalogueFeedAdapter):
    """Real-time partner API (≤1 h freshness).

    Contract: GET {PARTNER_API_URL}/prices?retailer=<name>&sku=<sku> (Bearer PARTNER_API_KEY)
    → 200 {"price": 4.5, "on_special": false, "captured_at": "2026-10-27T09:00:00"}, or 404 when
    the retailer doesn't stock it. Without a URL, or if the feed is down, the simulated price is
    used and labelled synthetic, so a fallback is never presented as a live quote."""

    def quote_for(self, product: Product, retailer: Retailer) -> QuoteData | None:
        settings = get_settings()
        if not settings.partner_api_url:
            return self._fetch(product, retailer)
        try:
            return self._fetch_live(product, retailer, settings)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            log.warning("Partner price feed failed for %s at %s (%s); using simulated price", product.sku, retailer.name, exc)
            return self._fetch(product, retailer)

    def _fetch_live(self, product: Product, retailer: Retailer, settings) -> QuoteData | None:
        headers = {"Authorization": f"Bearer {settings.partner_api_key}"} if settings.partner_api_key else {}
        response = httpx.get(
            f"{settings.partner_api_url.rstrip('/')}/prices", params={"retailer": retailer.name, "sku": product.sku},
            headers=headers, timeout=settings.partner_api_timeout_s,
        )
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise ValueError(f"HTTP {response.status_code} from the partner feed")
        body = response.json()
        price = float(body["price"])
        if price <= 0:
            raise ValueError(f"non-positive price {price}")
        captured = datetime.fromisoformat(body["captured_at"]) if body.get("captured_at") else datetime.now()
        return QuoteData(price=round(price, 2), on_special=bool(body.get("on_special", False)),
                         captured_at=captured, source=QuoteSource.live)


def source_for(retailer: Retailer) -> PriceSource:
    return PartnerApiAdapter() if retailer.source == "partner_api" else CatalogueFeedAdapter()
