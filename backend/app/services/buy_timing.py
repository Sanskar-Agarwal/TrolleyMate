"""Buy-timing intelligence (1.2.6) — a predictive service, not an LLM task.

Looks for a recurring weekday discount in a product's timestamped price history at
the basket's retailer and states the expected saving and how long to wait. Advice
never changes the basket. It abstains when there isn't enough history, for daily
staples (milk, bread...), and for all perishables. Advice built on demo history is labelled as such and is never worded as
an observed retailer forecast.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain import Basket, PriceQuote
from app.domain.enums import QuoteSource

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MIN_WEEKS = 6  # weeks of history needed before we predict anything
PATTERN_SHARE = 0.75  # the discount must show up on the same weekday in ≥75% of weeks
MIN_SAVING = 0.5
HISTORY_WINDOW = timedelta(weeks=8, days=1)
DEMO_NOTE = "Estimates use seeded price history, not observed retailer prices."


def is_demo(history: list[PriceQuote]) -> bool:
    """Demo history can't support a real forecast: the deployment says its history is generated,
    or the window contains synthetic quotes."""
    return get_settings().demo_price_history or any(q.source_type == QuoteSource.synthetic for q in history)


def history_summary(history: list[PriceQuote], weeks: int) -> dict:
    """The timestamped evidence behind a piece of advice."""
    return {
        "weeks": weeks,
        "quotes": len(history),
        "from": history[0].captured_at.isoformat() if history else None,
        "to": history[-1].captured_at.isoformat() if history else None,
        "demo": is_demo(history),
    }


def advise(db: Session, basket: Basket, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    advice = []
    for item in basket.items:
        if item.withheld:
            continue
        product = item.product
        base = {"item_id": item.id, "product": product.name}
        if product.perishable:
            advice.append({**base, "action": "skip", "reason": "Perishable product: timing advice does not apply."})
            continue
        if "daily" in product.tags:
            advice.append({**base, "action": "skip", "reason": "Needed day-to-day, so timing advice doesn't apply."})
            continue
        history = db.scalars(
            select(PriceQuote)
            .where(
                PriceQuote.product_id == product.id,
                PriceQuote.retailer_id == item.retailer_id,
                PriceQuote.captured_at >= now - HISTORY_WINDOW,
                PriceQuote.captured_at <= now,
            )
            .order_by(PriceQuote.captured_at)
        ).all()
        weeks = {q.captured_at.isocalendar()[:2] for q in history}
        summary = history_summary(history, len(weeks))
        base["history"] = summary
        if len(weeks) < MIN_WEEKS:
            advice.append({**base, "action": "none",
                           "reason": f"Not enough price history to predict ({len(weeks)} of {MIN_WEEKS} weeks needed)."})
            continue
        source = "Based on seeded historical prices" if summary["demo"] else "In recorded prices at this store"

        specials_by_day: dict[int, list[PriceQuote]] = defaultdict(list)
        for q in history:
            if q.on_special:
                specials_by_day[q.captured_at.weekday()].append(q)
        if not specials_by_day:
            advice.append({**base, "action": "buy_now", "reason": f"{source}, there was no recurring discount in the last 8 weeks."})
            continue

        day, quotes = max(specials_by_day.items(), key=lambda kv: len(kv[1]))
        share = len({q.captured_at.isocalendar()[:2] for q in quotes}) / len(weeks)
        if share < PATTERN_SHARE:
            advice.append({**base, "action": "buy_now", "reason": f"{source}, discounts were irregular; no reliable pattern."})
            continue

        special_price = round(sum(q.price for q in quotes) / len(quotes), 2)
        wait_days = (day - now.weekday()) % 7
        saving = round((item.pack_price - special_price) * item.quantity, 2)
        evidence = f"{source}, it was discounted on {len(quotes)} of the last {len(weeks)} {WEEKDAYS[day]}s"
        if wait_days == 0 or saving < MIN_SAVING:
            advice.append({**base, "action": "buy_now", "reason": f"{evidence}; today's price is already the best.", "pattern_day": WEEKDAYS[day]})
            continue
        outcome = (f"waiting {wait_days} day{'s' if wait_days != 1 else ''} would save about ${saving:.2f} if that pattern held"
                   if summary["demo"] else
                   f"waiting {wait_days} day{'s' if wait_days != 1 else ''} should save about ${saving:.2f}")
        advice.append(
            {
                **base,
                "action": "wait",
                "wait_days": wait_days,
                "wait_until": (now + timedelta(days=wait_days)).date().isoformat(),
                "pattern_day": WEEKDAYS[day],
                "expected_saving": saving,
                "expected_price": special_price,
                "confidence": round(share, 2),
                "reason": f"{evidence}, so {outcome}.",
            }
        )
    return advice
