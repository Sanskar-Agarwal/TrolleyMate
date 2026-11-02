"""UC-05 / 1.2.7 / 1.2.6 endpoints — catalogue, comparison, price history, buy timing.
Owner: Pricing & Editing (buy timing: Negotiation & Substitution)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.agents.context import AgentContext
from app.api.common import done, not_found, own_basket
from app.core.deps import agent_context
from app.domain import PriceQuote, Product
from app.services.buy_timing import DEMO_NOTE
from app.services.pricing.normalisation import UnitPrice

router = APIRouter(tags=["pricing"])


@router.get("/retailers")
def retailers(ctx: AgentContext = Depends(agent_context)) -> list[dict]:
    return [{"id": r.id, "name": r.name, "region": r.region, "source": r.source} for r in ctx.analyst.retailers]


@router.get("/products")
def products(
    q: str | None = None, category: str | None = None, ctx: AgentContext = Depends(agent_context)
) -> list[dict]:
    stmt = select(Product).order_by(Product.category, Product.name)
    if category:
        stmt = stmt.where(Product.category == category)
    rows = []
    for p in ctx.db.scalars(stmt):
        if q and q.lower() not in p.name.lower():
            continue
        prices = []
        for r in ctx.analyst.retailers:
            quote = ctx.analyst.current_quote(p, r, refresh=False)
            prices.append({
                "retailer_id": r.id, "retailer": r.name,
                "price": quote.price if quote else None,
                "unit_price_label": UnitPrice(quote.unit_price, quote.unit_basis).label() if quote and quote.unit_price else None,
                "status": quote.status if quote else "unavailable",
                "on_special": quote.on_special if quote else False,
            })
        rows.append({
            "id": p.id, "name": p.name, "brand": p.brand, "category": p.category, "tags": p.tags,
            "data_complete": p.data_complete, "ingredients": [i.name for i in p.ingredients], "prices": prices,
        })
    return rows


@router.get("/products/{product_id}/history")
def price_history(product_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    p = ctx.db.get(Product, product_id)
    if p is None:
        raise not_found("Product")
    quotes = ctx.db.scalars(select(PriceQuote).where(PriceQuote.product_id == p.id).order_by(PriceQuote.captured_at)).all()
    names = {r.id: r.name for r in ctx.analyst.retailers}
    return {
        "product": {"id": p.id, "name": p.name},
        "quotes": [
            {"retailer": names[q.retailer_id], "price": q.price, "on_special": q.on_special,
             "captured_at": q.captured_at.isoformat(), "status": q.status}
            for q in quotes
        ],
    }


@router.get("/baskets/{basket_id}/comparison")
def comparison(basket_id: int, baseline_id: int | None = Query(default=None), ctx: AgentContext = Depends(agent_context)) -> dict:
    return done(ctx, ctx.analyst.compare(own_basket(ctx, basket_id), baseline_id))


@router.get("/baskets/{basket_id}/buy-timing")
def buy_timing(basket_id: int, ctx: AgentContext = Depends(agent_context)) -> dict:
    advice = ctx.analyst.buy_timing(own_basket(ctx, basket_id))
    demo = any(a.get("history", {}).get("demo") for a in advice)
    return done(ctx, {"advice": advice, "demo_history": demo, "history_note": DEMO_NOTE if demo else None})
