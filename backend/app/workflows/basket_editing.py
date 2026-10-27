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

    # Pantry/snack items aren't solver candidates: they're added directly after the solve. Keep the
    # ones already in the basket (unless this edit removes or reduces them) and reserve their cost,
    # so the solved basket plus these extras still fits the budget.
    extras = {pid: q for pid, q in current.items() if _category(db, pid) in ("pantry", "snack") and pid not in excluded}
    for pid in [p for p in min_qty if _category(db, p) in ("pantry", "snack")]:
        extras[pid] = max(extras.get(pid, 0), min_qty.pop(pid))
    for pid, hi in max_qty.items():
        if pid in extras:
            extras[pid] = min(extras[pid], hi)
    extras = {pid: q for pid, q in extras.items() if q > 0}
    reserve = _extras_cost(agent, extras)
    budget = payload.get("budget")
    if budget is not None and reserve > float(budget) + 1e-6:
        return {
            "status": "conflict",
            "message": f"Those extras would cost ${reserve:.2f}, more than your ${float(budget):.2f} budget, "
                       "so I've left the basket as it was.",
            "suggestions": [],
        }

    from app.workflows import basket_builder

    outcome = basket_builder.build(
        agent, session, basket.goal, payload_override=payload, origin="edit",
        min_qty=min_qty, max_qty=max_qty, exclude_products=excluded, prefer=set(current) - excluded, reserve=reserve,
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
    return {"status": "ok", "basket": new_basket, "applied": applied, "conflicts": conflicts,
            "diff": basket_diff(basket, new_basket)}


def basket_diff(before: Basket, after: Basket) -> dict:
    """What a chat edit actually changed: items added, removed or re-quantified, and the total."""
    old = {i.product.name: i.quantity for i in before.items if not i.withheld}
    new = {i.product.name: i.quantity for i in after.items if not i.withheld}
    return {
        "added": [{"product": n, "quantity": q} for n, q in new.items() if n not in old],
        "removed": [{"product": n, "quantity": q} for n, q in old.items() if n not in new],
        "changed": [{"product": n, "from": old[n], "to": q} for n, q in new.items() if n in old and old[n] != q],
        "total_before": round(before.total, 2), "total_after": round(after.total, 2),
    }


def describe_diff(diff: dict) -> str:
    parts = []
    if diff["added"]:
        parts.append("Added " + ", ".join(f"{d['product']} ×{d['quantity']}" for d in diff["added"]))
    if diff["removed"]:
        parts.append("Removed " + ", ".join(d["product"] for d in diff["removed"]))
    if diff["changed"]:
        parts.append("Changed " + ", ".join(f"{d['product']} ×{d['from']}→×{d['to']}" for d in diff["changed"]))
    delta = diff["total_after"] - diff["total_before"]
    parts.append(f"Total ${diff['total_before']:.2f} → ${diff['total_after']:.2f} ({'+' if delta >= 0 else '−'}${abs(delta):.2f})")
    return ". ".join(parts) + "."


def _category(db, product_id: int) -> str:
    from app.domain import Product

    return db.get(Product, product_id).category


def _extras_cost(agent, extras: dict[int, int]) -> float:
    from app.domain import Product

    total = 0.0
    for pid, qty in extras.items():
        offer = agent.ctx.analyst.offers([agent.db.get(Product, pid)])
        if offer:
            total += offer[0].price * qty
    return round(total, 2)


def _add_extras(agent, basket: Basket, extras: dict[int, int]) -> None:
    from app.domain import BasketItem, Product

    for pid, qty in extras.items():
        product = agent.db.get(Product, pid)
        offer = agent.ctx.analyst.offers([product])
        if not offer:
            continue
        o = offer[0]
        basket.add_item(BasketItem(product_id=pid, retailer_id=o.retailer.id, quote_id=o.quote_id, quantity=qty,
                                   pack_price=o.price, line_total=round(o.price * qty, 2), compliance=ItemCompliance.compliant,
                                   rationale="Added at your request"))
    agent.db.flush()
    basket.recalc_total()
