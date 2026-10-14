"""Buy-timing intelligence (1.2.6) — a predictive service, not an LLM task.

Looks for a recurring weekday discount in a product's price history at the
basket's retailer. Advice never changes the basket. Items without enough history
get no advice; daily staples (milk, bread...) are left out entirely.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import Basket, PriceQuote

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MIN_WEEKS = 6  # weeks of history needed before we predict anything
PATTERN_SHARE = 0.75  # the discount must show up on the same weekday in ≥75% of weeks
MIN_SAVING = 0.5


def advise(db: Session, basket: Basket, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    advice = []
    for item in basket.items:
        if item.withheld:
            continue
        product = item.product
        base = {"item_id": item.id, "product": product.name}
        if "daily" in product.tags:
            advice.append({**base, "action": "skip", "reason": "Needed day-to-day, so timing advice doesn't apply."})
            continue
        history = db.scalars(
            select(PriceQuote)
            .where(
                PriceQuote.product_id == product.id,
                PriceQuote.retailer_id == item.retailer_id,
                PriceQuote.captured_at >= now - timedelta(weeks=8, days=1),
            )
            .order_by(PriceQuote.captured_at)
        ).all()
        weeks = {q.captured_at.isocalendar()[:2] for q in history}
        if len(weeks) < MIN_WEEKS:
            advice.append({**base, "action": "none", "reason": "Not enough price history to predict."})
            continue

        specials_by_day: dict[int, list[PriceQuote]] = defaultdict(list)
        for q in history:
            if q.on_special:
                specials_by_day[q.captured_at.weekday()].append(q)
        if not specials_by_day:
            advice.append({**base, "action": "buy_now", "reason": "No recurring discount in the last 8 weeks."})
            continue

        day, quotes = max(specials_by_day.items(), key=lambda kv: len(kv[1]))
        share = len({q.captured_at.isocalendar()[:2] for q in quotes}) / len(weeks)
        if share < PATTERN_SHARE:
            advice.append({**base, "action": "buy_now", "reason": "Discounts are irregular; no reliable pattern."})
            continue

        special_price = round(sum(q.price for q in quotes) / len(quotes), 2)
        wait_days = (day - now.weekday()) % 7
        saving = round((item.pack_price - special_price) * item.quantity, 2)
        evidence = f"Discounted on {len(quotes)} of the last {len(weeks)} {WEEKDAYS[day]}s"
        if wait_days == 0 or saving < MIN_SAVING:
            advice.append({**base, "action": "buy_now", "reason": f"{evidence}; today's price is already the best.", "pattern_day": WEEKDAYS[day]})
            continue
        if product.perishable and wait_days > product.shelf_life_days:
            advice.append({**base, "action": "buy_now", "reason": f"{evidence}, but it wouldn't keep that long."})
            continue
        advice.append(
            {
                **base,
                "action": "wait",
                "wait_days": wait_days,
                "pattern_day": WEEKDAYS[day],
                "expected_saving": saving,
                "expected_price": special_price,
                "confidence": round(share, 2),
                "reason": f"{evidence}. Waiting {wait_days} day{'s' if wait_days != 1 else ''} should save about ${saving:.2f}.",
            }
        )
    return advice
