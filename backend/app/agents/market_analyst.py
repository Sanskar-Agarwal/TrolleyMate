"""«worker» MarketAnalystAgent — pricing, retailer comparison, buy-timing (UC-05, 1.2.6–1.2.8).

The computational core is deterministic (Section 4.1): ingestion, unit-price
normalisation, savings arithmetic and timing forecasts are plain services. The LLM
is used only to explain *why* one option is cheaper.
"""

from __future__ import annotations

from sqlalchemy import select

from app.agents.base import Agent
from app.core.config import get_settings
from app.domain import Basket, PriceQuote, Product, Retailer
from app.domain.enums import QuoteStatus
from app.optimisation.types import Candidate
from app.services import buy_timing
from app.services.pricing.normalisation import normalise
from app.services.pricing.price_sources import source_for


class MarketAnalystAgent(Agent):
    role_name = "AI Market Analyst"
    key = "market_analyst"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._retailers: list[Retailer] | None = None
        self.refreshed = 0
        self.unavailable = 0

    @property
    def retailers(self) -> list[Retailer]:
        if self._retailers is None:
            self._retailers = list(self.db.scalars(select(Retailer).order_by(Retailer.id)))
        return self._retailers

    # --- Quotes (State machine 9.3) ---------------------------------------

    def current_quote(self, product: Product, retailer: Retailer, *, refresh: bool = True) -> PriceQuote | None:
        quote = self.db.scalar(
            select(PriceQuote)
            .where(
                PriceQuote.product_id == product.id,
                PriceQuote.retailer_id == retailer.id,
                PriceQuote.status != QuoteStatus.superseded,
            )
            .order_by(PriceQuote.captured_at.desc())
            .limit(1)
        )
        return self._usable(quote, product, retailer, refresh)

    def _latest_quotes(self, product_ids: list[int]) -> dict[tuple[int, int], PriceQuote]:
        """Every product's current quote at every retailer, in one query: (product_id, retailer_id) → quote."""
        rows = self.db.scalars(
            select(PriceQuote)
            .where(PriceQuote.product_id.in_(product_ids), PriceQuote.status != QuoteStatus.superseded)
            .order_by(PriceQuote.captured_at)
        )
        return {(q.product_id, q.retailer_id): q for q in rows}  # ascending, so the latest wins

    def _usable(self, quote: PriceQuote | None, product: Product, retailer: Retailer, refresh: bool) -> PriceQuote | None:
        """None if there's no price; a refreshed quote if this one is stale (State machine 9.3)."""
        if quote is None or quote.status == QuoteStatus.unavailable:
            return None
        max_age = get_settings().price_max_age_hours
        if refresh and (quote.status == QuoteStatus.stale or quote.is_stale(max_age)):
            return self._refresh(quote, product, retailer)
        return quote

    def _refresh(self, old: PriceQuote, product: Product, retailer: Retailer) -> PriceQuote | None:
        data = source_for(retailer).quote_for(product, retailer)
        if data is None:
            old.mark_unavailable("Retailer feed returned no price for this product")
            self.unavailable += 1
            return None
        unit = normalise(data.price, product.pack_size, product.unit)
        new = PriceQuote(
            product_id=product.id, retailer_id=retailer.id, price=data.price,
            unit_price=unit.value if unit else None, unit_basis=unit.basis if unit else "",
            on_special=data.on_special, captured_at=data.captured_at, status=QuoteStatus.fresh,
        )
        self.db.add(new)
        self.db.flush()
        old.supersede(new)
        self.refreshed += 1
        return new

    def offers(self, products: list[Product], compliance: dict[int, str] | None = None) -> list[Candidate]:
        """Cheapest current offer per product across retailers (the solver's candidate set)."""
        out: list[Candidate] = []
        latest = self._latest_quotes([p.id for p in products])
        for product in products:
            best: tuple[PriceQuote, Retailer] | None = None
            for retailer in self.retailers:
                quote = self._usable(latest.get((product.id, retailer.id)), product, retailer, refresh=True)
                if quote and quote.unit_price is not None and (best is None or quote.price < best[0].price):
                    best = (quote, retailer)
            if best:
                q, r = best
                out.append(
                    Candidate(
                        product=product, retailer=r, price=q.price, quote_id=q.id, unit_price=q.unit_price,
                        unit_basis=q.unit_basis, on_special=q.on_special,
                        compliance=(compliance or {}).get(product.id, "compliant"),
                    )
                )
        return out

    # --- Comparison & savings (UC-05) -------------------------------------

    def compare(self, b: Basket, baseline_id: int | None = None) -> dict:
        retailers = self.retailers
        baseline = next((r for r in retailers if r.id == baseline_id), retailers[0])
        rows, totals, unpriced = [], {r.id: 0.0 for r in retailers}, {r.id: [] for r in retailers}
        split_total, winners = 0.0, {r.name: 0 for r in retailers}
        latest = self._latest_quotes([i.product_id for i in b.items])

        for item in b.items:
            if item.withheld:
                continue
            prices = {}
            for r in retailers:
                q = self._usable(latest.get((item.product_id, r.id)), item.product, r, refresh=True)
                if q is None:
                    unpriced[r.id].append(item.product.name)
                    continue
                line = round(q.price * item.quantity, 2)
                prices[r.id] = {"pack_price": q.price, "line": line, "unit_price": q.unit_price, "unit_basis": q.unit_basis, "on_special": q.on_special}
                totals[r.id] += line
            if prices:
                cheapest = min(prices, key=lambda rid: prices[rid]["line"])
                split_total += prices[cheapest]["line"]
                winners[next(r.name for r in retailers if r.id == cheapest)] += 1
            else:
                cheapest = None
            rows.append({"item_id": item.id, "product": item.product.name, "quantity": item.quantity, "prices": prices, "cheapest_retailer_id": cheapest})

        base_total = round(totals[baseline.id], 2)

        def option(name: str, total: float, rid: int | None, missing: list[str], is_split: bool = False) -> dict:
            saving = round(base_total - total, 2)
            return {
                "name": name, "retailer_id": rid, "total": round(total, 2), "saving": saving,
                "saving_pct": round(saving / base_total * 100, 1) if base_total else 0.0,
                "complete": not missing, "unpriced": missing, "is_split": is_split,
            }

        options = [option(r.name, totals[r.id], r.id, unpriced[r.id]) for r in retailers]
        options.append(option("Split basket (cheapest per item)", split_total, None, [], True))
        complete = [o for o in options if o["complete"]]
        cheapest = min(complete, key=lambda o: o["total"]) if complete else None

        insight = None
        if cheapest:
            result = self.think(
                "market_insight",
                {
                    "baseline": baseline.name, "cheapest": cheapest, "item_winners": winners,
                    "options": [{k: o[k] for k in ("name", "total", "saving", "saving_pct", "complete")} for o in options],
                    "unpriced": sorted({p for o in options for p in o["unpriced"]}),
                },
            )
            insight = result.data
            self.log(
                "compare_prices",
                f"{cheapest['name']} cheapest at ${cheapest['total']:.2f} vs {baseline.name} ${base_total:.2f}",
                rationale=insight, basket_id=b.id, session_id=b.session_id, llm=result, confidence=1.0,
            )
        else:
            self.log("compare_prices", "Comparison incomplete: key items unpriced at every retailer", basket_id=b.id, session_id=b.session_id)

        return {
            "basket_id": b.id,
            "baseline": {"id": baseline.id, "name": baseline.name, "total": base_total},
            "options": options,
            "rows": rows,
            "retailers": [{"id": r.id, "name": r.name, "source": r.source} for r in retailers],
            "cheapest": cheapest,
            "insight": insight,
            "complete": cheapest is not None,
            "refreshed_quotes": self.refreshed,
        }

    def explain_difference(self, product: Product) -> str:
        quotes = [(r, self.current_quote(product, r)) for r in self.retailers]
        priced = sorted([(r, q) for r, q in quotes if q], key=lambda rq: rq[1].price)
        if not priced:
            return f"No current prices for {product.name}."
        lo, hi = priced[0], priced[-1]
        return f"{product.name} is ${lo[1].price:.2f} at {lo[0].name} vs ${hi[1].price:.2f} at {hi[0].name}."

    # --- Buy timing (1.2.6) -----------------------------------------------

    def buy_timing(self, b: Basket) -> list[dict]:
        advice = buy_timing.advise(self.db, b)
        waits = [a for a in advice if a["action"] == "wait"]
        self.log(
            "buy_timing",
            f"{len(waits)} item(s) worth waiting for" if waits else "No timing advice worth acting on",
            rationale="; ".join(a["reason"] for a in waits)[:500],
            basket_id=b.id, session_id=b.session_id, payload={"advice": advice},
        )
        return advice
