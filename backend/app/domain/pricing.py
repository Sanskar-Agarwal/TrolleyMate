"""Domain::Pricing — Retailer, PriceQuote. (SavingsReport is computed; see schemas/pricing.py.)"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.domain.enums import QuoteStatus


class Retailer(Base):
    __tablename__ = "retailers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    region: Mapped[str] = mapped_column(String(80), default="Sydney Metro")
    # Which PriceSource adapter feeds this retailer: catalogue | partner_api
    source: Mapped[str] = mapped_column(String(20), default="catalogue")


class PriceQuote(Base):
    """One captured price of one product at one retailer. Never overwritten (State machine 9.3)."""

    __tablename__ = "price_quotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    retailer_id: Mapped[int] = mapped_column(ForeignKey("retailers.id"), index=True)
    price: Mapped[float] = mapped_column(Float)
    # Normalised price per 100 g / 100 mL / each (1.2.7). Null if it could not be normalised.
    unit_price: Mapped[float | None] = mapped_column(Float, default=None)
    unit_basis: Mapped[str] = mapped_column(String(10), default="100g")
    on_special: Mapped[bool] = mapped_column(Boolean, default=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(20), default=QuoteStatus.fresh)
    superseded_by_id: Mapped[int | None] = mapped_column(Integer, default=None)
    unavailable_reason: Mapped[str | None] = mapped_column(String(200), default=None)

    retailer: Mapped[Retailer] = relationship()

    def is_stale(self, max_age_hours: int, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        return self.captured_at < now - timedelta(hours=max_age_hours)

    def supersede(self, newer: PriceQuote) -> None:
        self.status = QuoteStatus.superseded
        self.superseded_by_id = newer.id

    def mark_unavailable(self, reason: str) -> None:
        self.status = QuoteStatus.unavailable
        self.unavailable_reason = reason
