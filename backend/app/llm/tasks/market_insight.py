"""UC-05 — the AI Market Analyst explains why one retailer comes out cheaper. Owner: Pricing & Editing."""

from __future__ import annotations

import json
import re
from decimal import Decimal

from app.llm.tasks._base import Task

SYSTEM = """You are the AI Market Analyst of Trolley Mate. You are given a computed
price comparison between grocers. Write a short insight for the shopper.

Surface ONE thing a shopper would likely miss from the numbers alone. Good candidates:
- The saving is driven mostly by a single item.
- Specials or temporary discounts are distorting the total, so the cheapest store
  today may not be cheapest next week.
- A store is cheapest overall but noticeably more expensive on specific items.
- The split basket saves only a small amount compared with the single cheapest
  store, which may not justify the extra trip.
- Price-per-unit tells a different story from shelf price (different pack sizes).
- Items are missing or unavailable at one store, making its total look lower than
  it really is.
- The cheaper basket relies on lower-tier versions of items (house brand vs name
  brand, different grade or variety), so it isn't a like-for-like comparison. Only
  point this out when the product names or attributes in the data show it.

Pick the most significant one. If nothing stands out, say in one sentence that the
totals are a fair reflection of the comparison. Do not manufacture an insight.

Rules:
- Do not restate what the numbers already show (e.g. "Store A is $4.20 cheaper").
- Use only the numbers provided. Never compute or invent new prices, savings or
  percentages. Quote figures exactly as given.
- Keep it to 1-2 sentences in plain language, with no hedging.
- No markdown.

The grocers are fictional. Base everything only on the data provided. Do not use
real-world knowledge of supermarket chains, and do not assume or invent anything
about these stores that is not in the data, including their quality, reputation,
location, distance, opening hours, loyalty programs or typical pricing. If a point
depends on information that is not in the data, such as how far apart the stores
are, either skip it or frame it as something for the shopper to weigh (e.g. "worth
it only if both stores are on your way")."""


def build_user(ctx: dict) -> str:
    return json.dumps(ctx, indent=1)


def mock(ctx: dict) -> str:
    best = ctx["cheapest"]
    lines = [f"{best['name']} is the cheapest option at ${best['total']:.2f}, saving ${best['saving']:.2f} ({best['saving_pct']:.0f}%) against {ctx['baseline']}."]
    winners = ctx.get("item_winners") or {}
    if winners:
        top = max(winners.items(), key=lambda kv: kv[1])
        lines.append(f"{top[0]} has the lowest price on {top[1]} of {sum(winners.values())} items.")
    if best.get("is_split"):
        lines.append("The split basket means shopping at more than one store, so weigh the saving against the extra trip.")
    if ctx.get("unpriced"):
        lines.append(f"{len(ctx['unpriced'])} item(s) had no current price at some stores, so those totals are incomplete.")
    return " ".join(lines)


def grounded_insight(text: str, ctx: dict) -> str:
    """Do not display model-invented money/percentage figures as computed savings."""
    money = {Decimal(str(o[k])) for o in ctx["options"] for k in ("total", "saving") if o.get(k) is not None}
    percentages = {Decimal(str(o["saving_pct"])) for o in ctx["options"] if o.get("saving_pct") is not None}
    extra = ctx.get("split_saving_vs_cheapest_store")
    if extra is not None:
        money.add(Decimal(str(extra)))
    quoted_money = [Decimal(n.replace(",", "")) for n in re.findall(r"\$\s*(-?[\d,]+(?:\.\d+)?)", text)]
    quoted_percent = [Decimal(n) for n in re.findall(r"(-?\d+(?:\.\d+)?)\s*%", text)]
    if any(n not in money for n in quoted_money) or any(n not in percentages for n in quoted_percent):
        return mock(ctx)
    return text


TASK = Task(name="market_insight", system=SYSTEM, build_user=build_user, mock=mock)
