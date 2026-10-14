"""UC-02 — Optimise basket. The primary, workflow-controlled path of Figure 4.2:

  (1) Market Analyst prices the catalogue      → candidate offers
  (2) Nutrition & Compliance screens candidates → violations removed, uncertain flagged
  (3) BasketOptimiser solves under constraints  → basket or infeasible
  (4) Nutrition & Compliance verifies basket    → passed / escalated (items withheld)
  (5) Personal Shopper presents it with an explanation

If (3) is infeasible, UC-03 negotiation is invoked instead (extension 3a).
Owner: Intake & Optimisation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select

from app.domain import Basket, BasketItem, ConstraintSetRecord, ShoppingSession
from app.domain.enums import BasketStatus, ItemCompliance, SessionStatus, VerdictStatus
from app.domain.requests_constraints import ConstraintSet
from app.optimisation import BasketOptimiser, Requirements, strategy_for
from app.services.catalogue import disliked_by, optimisable_products
from app.services.session_state import active_constraints, household_of, latest_basket


class BuildError(ValueError):
    pass


@dataclass
class BuildOutcome:
    status: str  # ok | infeasible
    basket: Basket | None = None
    negotiation: dict | None = None
    excluded: list[dict] = field(default_factory=list)


def build(
    agent,
    session: ShoppingSession,
    goal: str | None = None,
    *,
    payload_override: dict | None = None,
    origin: str = "intake",
    min_qty: dict[int, int] | None = None,
    max_qty: dict[int, int] | None = None,
    exclude_products: set[int] | None = None,
    prefer: set[int] | None = None,
) -> BuildOutcome:
    db, ctx = agent.db, agent.ctx
    record = active_constraints(db, session)
    if record is None:
        raise BuildError("Confirm your shopping constraints before building a basket.")
    payload = payload_override or record.payload
    cs = ConstraintSet.from_payload(payload, version=record.version)
    goal = goal or session.goal
    strategy = strategy_for(goal)
    household = household_of(db, session)
    session.status = SessionStatus.optimising

    # (2) Screen first, so we only price products that could ever be bought.
    restrictions = ctx.compliance.restrictions_for(household, payload)
    products = [p for p in optimisable_products(db) if p.id not in (exclude_products or set())]
    preferences = payload.get("preferences", [])
    skipped_prefs = {p.id: disliked_by(p, preferences) for p in products}
    products = [p for p in products if not skipped_prefs[p.id] or p.id in (min_qty or {})]
    screening = ctx.compliance.screen(products, restrictions, household_id=household.id, session_id=session.id)
    allowed = [p for p in products if screening[p.id].status != ItemCompliance.violation]
    excluded = [screening[p.id].as_dict() for p in products if screening[p.id].status == ItemCompliance.violation]

    # (1) Price what's left.
    candidates = ctx.analyst.offers(allowed, {pid: f.status for pid, f in screening.items()})
    ctx.analyst.log(
        "price_candidates",
        f"Priced {len(candidates)} products across {len(ctx.analyst.retailers)} retailers",
        rationale=f"Refreshed {ctx.analyst.refreshed} stale quote(s); {ctx.analyst.unavailable} unavailable",
        session_id=session.id, confidence=1.0,
    )

    # (3) Solve.
    req = Requirements.from_constraints(cs)
    optimiser = BasketOptimiser()
    result = optimiser.solve(req, strategy, candidates, min_qty=min_qty, max_qty=max_qty, prefer=prefer)
    if not result.feasible:
        from app.workflows import negotiation

        info = negotiation.analyse(agent, session, cs, req, strategy, candidates, result.message)
        if payload_override is None:
            # The confirmed request itself can't be met. (A failed edit or trade-off
            # leaves the request — and the current basket — as they were.)
            for r in session.requests:
                if r.status == "confirmed" and r.id == record.request_id:
                    r.mark_infeasible()
        has_basket = latest_basket(db, session.id) is not None
        session.status = SessionStatus.basket_ready if has_basket else SessionStatus.open
        return BuildOutcome(status="infeasible", negotiation=info, excluded=excluded)

    # Persist a new constraint version only now that the edit/negotiation is known to be feasible.
    if payload_override is not None:
        record = _new_version(db, session, payload_override, origin)

    for old in db.scalars(select(Basket).where(Basket.session_id == session.id, Basket.status != BasketStatus.superseded)):
        old.status = BasketStatus.superseded

    basket = Basket(session_id=session.id, constraint_set_id=record.id, goal=goal, budget=req.budget, status=BasketStatus.optimised)
    db.add(basket)
    alternatives: dict[str, list[str]] = {}
    for c, qty in sorted(result.items, key=lambda cq: (cq[0].product.category, cq[0].product.name)):
        reason = strategy.item_reason(c)
        if c.on_special:
            reason += "; on special this week"
        basket.add_item(
            BasketItem(
                product_id=c.product.id, retailer_id=c.retailer.id, quote_id=c.quote_id, quantity=qty,
                pack_price=c.price, line_total=round(c.price * qty, 2), rationale=reason,
            )
        )
        alternatives[str(c.product.id)] = [
            f"{o.product.name} (${o.price:.2f})" for o in candidates
            if o.product.category == c.product.category and o.product.id != c.product.id
        ][:3]
    db.flush()
    basket.recalc_total()

    # (4) Verify.
    verdict = ctx.compliance.verify(basket, household, payload, req)
    basket.status = BasketStatus.pending_review if verdict.status == VerdictStatus.escalated else BasketStatus.verified
    basket.recalc_total()
    nutrition = ctx.compliance.assess_nutrition(basket, req)

    # (5) Present.
    withheld = [i.product.name for i in basket.items if i.withheld]
    facts = {
        "goal": goal,
        "strategy": strategy.label,
        "budget": req.budget,
        "total": basket.total,
        "person_meals": req.person_meals,
        "restrictions": [r["label"] for r in restrictions],
        "nutrition": nutrition["provided"],
        "nutrition_adequate": nutrition["adequate"],
        "excluded": [f"{e['product']} ({e['findings'][0]['detail']})" for e in excluded if e["findings"]][:6],
        "skipped_for_preferences": sorted({v for v in skipped_prefs.values() if v}),
        "withheld": withheld,
        "items": [{"name": i.product.name, "qty": i.quantity, "reason": i.rationale} for i in basket.items],
    }
    basket.notes = {
        "facts": facts,
        "requirements": req.as_dict(),
        "nutrition": nutrition,
        "metrics": result.metrics,
        "solver_ms": result.solver_ms,
        "verdict_id": verdict.id,
        "verdict": verdict.status,
        "alternatives": alternatives,
        "excluded": excluded,
        "notifications": [f"{name} is held until a dietitian confirms it's safe for your household." for name in withheld],
    }
    explanation = ctx.manager.explain_for(basket)  # grounded in the facts + audit trail written above
    agent.log(
        "optimise_basket",
        f"{strategy.label} basket: {len(basket.items)} items, ${basket.total:.2f} of ${req.budget or 0:.2f}",
        rationale=f"Solver {result.solver_ms} ms; verdict {verdict.status}", confidence=verdict.confidence,
        session_id=session.id, basket_id=basket.id, payload={"metrics": result.metrics},
    )
    if explanation["available"]:
        basket.notes = {**basket.notes, "summary": explanation["text"]}
    session.status = SessionStatus.basket_ready
    session.goal = goal
    return BuildOutcome(status="ok", basket=basket, excluded=excluded)


def _new_version(db, session: ShoppingSession, payload: dict, origin: str) -> ConstraintSetRecord:
    version = (db.scalar(select(func.max(ConstraintSetRecord.version)).where(ConstraintSetRecord.session_id == session.id)) or 0) + 1
    record = ConstraintSetRecord(session_id=session.id, version=version, confirmed_at=datetime.now(), payload=payload, origin=origin)
    db.add(record)
    db.flush()
    session.activate(record)
    return record


def current_basket(agent, session: ShoppingSession) -> Basket | None:
    return latest_basket(agent.db, session.id)
