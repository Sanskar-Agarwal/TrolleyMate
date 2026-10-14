"""UC-05 — the AI Market Analyst explains why one retailer comes out cheaper. Owner: Pricing & Editing."""

from __future__ import annotations

import json

from app.llm.tasks._base import Task

SYSTEM = """You are the AI Market Analyst of Trolley Mate. Given a computed price
comparison, explain in 2-3 sentences why the cheapest option is cheapest and what
the shopper gives up (e.g. visiting two stores). Use only the numbers provided —
never compute or invent new prices. No markdown."""


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


TASK = Task(name="market_insight", system=SYSTEM, build_user=build_user, mock=mock)
