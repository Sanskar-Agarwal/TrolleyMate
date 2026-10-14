"""UC-09 — Conversational basket editing (1.2.9). Owner: Pricing & Editing.

The LLM turns "replace the beef with chicken and make it $10 cheaper" into
structured operations; deterministic code maps them onto products and re-runs
the optimiser with those pins. If the edit can't be satisfied, nothing changes
and the shopper gets the conflict and the closest valid alternatives.
"""

from __future__ import annotations

from app.domain import Basket, ShoppingSession
from app.domain.enums import ItemCompliance
from app.services.catalogue import find_products, match_item
from app.services.session_state import active_constraints, household_of


def edit(agent, basket: Basket, text: str) -> dict:
    db, ctx = agent.db, agent.ctx
    session = db.get(ShoppingSession, basket.session_id)
    result = agent.think("parse_edit", {"items": [i.product.name for i in basket.items], "text": text})
    plan = result.data
    agent.log("parse_edit", plan.get("summary") or "No operations found", session_id=session.id, basket_id=basket.id, llm=result)

    if not plan["operations"] and not plan.get("budget_change"):
        return {"status": "clarify", "question": plan.get("clarification_question") or "What would you like to change?"}

    record = active_constraints(db, session)
    payload = dict(record.payload)
    household = household_of(db, session)
    restrictions = ctx.compliance.restrictions_for(household, payload)
    current = {i.product_id: i.quantity for i in basket.items}
    min_qty: dict[int, int] = {}
    max_qty: dict[int, int] = {}
    excluded: set[int] = set()
    applied, conflicts = [], []

    def compliant_match(description: str, not_this: int | None = None):
        for p in find_products(db, description, limit=6):
            if p.id != not_this and ctx.compliance.screen_product(p, restrictions, household.id).status == ItemCompliance.compliant:
                return p
        return None

    for op in plan["operations"]:
        kind, target, replacement = op["op"], op.get("target"), op.get("replacement")
        item = match_item(basket, target) if target else None
        if kind in ("remove", "replace", "increase", "decrease") and item is None:
            conflicts.append(f"I couldn't find '{target}' in your basket.")
            continue
        if kind == "remove":
            excluded.add(item.product_id)
            applied.append(f"removed {item.product.name}")
        elif kind == "replace":
            product = compliant_match(replacement or "", not_this=item.product_id)
            if product is None:
                conflicts.append(f"No '{replacement}' option is safe for your household's dietary rules.")
                continue
            excluded.add(item.product_id)
            min_qty[product.id] = max(current.get(product.id, 0) + 1, item.quantity if product.category == item.product.category else 1)
            applied.append(f"replaced {item.product.name} with {product.name}")
        elif kind == "add":
            product = compliant_match(replacement or target or "")
            if product is None:
                conflicts.append(f"No '{replacement}' option is safe for your household's dietary rules.")
                continue
            min_qty[product.id] = 1
            applied.append(f"added {product.name}")
        elif kind == "increase":
            min_qty[item.product_id] = item.quantity + 1
            applied.append(f"more {item.product.name}")
        elif kind == "decrease":
            max_qty[item.product_id] = max(0, item.quantity - 1)
            applied.append(f"less {item.product.name}")

    budget_change = plan.get("budget_change")
    if budget_change:
        old = float(payload.get("budget") or basket.total)
        new = old + budget_change["amount"] if budget_change["mode"] == "delta" else budget_change["amount"]
        if budget_change["mode"] == "delta" and budget_change["amount"] < 0:
            new = min(new, basket.total + budget_change["amount"])  # "$10 cheaper" means cheaper than now
        payload["budget"] = round(max(new, 1.0), 2)
        applied.append(f"budget ${payload['budget']:.2f}")

    if conflicts and not applied:
        return {"status": "conflict", "message": " ".join(conflicts), "suggestions": []}

    # Pantry/snack additions aren't solver candidates: add them directly after the solve.
    extras = {pid: q for pid, q in min_qty.items() if _category(db, pid) in ("pantry", "snack")}
    for pid in extras:
        min_qty.pop(pid)

    from app.workflows import basket_builder

    outcome = basket_builder.build(
        agent, session, basket.goal, payload_override=payload, origin="edit",
        min_qty=min_qty, max_qty=max_qty, exclude_products=excluded, prefer=set(current) - excluded,
    )
    if outcome.status != "ok":
        neg = outcome.negotiation or {}
        return {
            "status": "conflict",
            "message": "That change can't be made without breaking your other constraints, so I've left the basket as it was. "
                       + (neg.get("message") or ""),
            "suggestions": neg.get("options", []),
        }
    new_basket = outcome.basket
    if extras:
        _add_extras(agent, new_basket, extras)
    return {"status": "ok", "basket": new_basket, "applied": applied, "conflicts": conflicts}


def _category(db, product_id: int) -> str:
    from app.domain import Product

    return db.get(Product, product_id).category


def _add_extras(agent, basket: Basket, extras: dict[int, int]) -> None:
    from app.domain import BasketItem, Product

    for pid, qty in extras.items():
        product = agent.db.get(Product, pid)
        offer = agent.ctx.analyst.offers([product])
        if not offer:
            continue
        o = offer[0]
        basket.add_item(BasketItem(product_id=pid, retailer_id=o.retailer.id, quote_id=o.quote_id, quantity=qty,
                                   pack_price=o.price, line_total=o.price * qty, compliance=ItemCompliance.compliant,
                                   rationale="Added at your request"))
    agent.db.flush()
    basket.recalc_total()
