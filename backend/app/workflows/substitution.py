"""UC-04 — Smart substitution with stated trade-off (Activity 7.2, Sequence 8.2,
State machine 9.2). Owner: Negotiation & Substitution.

Candidates are compliance-checked before the shopper ever sees them. A declined
swap is remembered for the session so it isn't offered again. If nothing viable
exists the item is removed and the shopper is told.
"""

from __future__ import annotations

from app.domain import Basket, BasketItem, Product, Substitution
from app.domain.enums import BasketStatus, ItemCompliance, SubReason, SubStatus
from app.services.catalogue import optimisable_products, product_tokens
from app.services.dietary_rules import RESTRICTION_RULES
from app.services.session_state import active_constraints, household_of


class SubstitutionError(ValueError):
    pass


def propose(agent, item: BasketItem, reason: str = SubReason.user_requested) -> Substitution:
    db, ctx = agent.db, agent.ctx
    from app.domain import ShoppingSession

    basket: Basket = item.basket
    session = db.get(ShoppingSession, basket.session_id)
    household = household_of(db, session)
    payload = (active_constraints(db, session).payload if session.active_constraint_set_id else {})
    restrictions = ctx.compliance.restrictions_for(household, payload)
    rejected = {(a, b) for a, b in session.rejected_swaps}

    sub = Substitution(session_id=session.id, basket_item_id=item.id, original_product_id=item.product_id, reason=reason)
    db.add(sub)

    # Identify candidates in the same category; ranking below prefers the same substitution group.
    original = item.product
    in_basket = {i.product_id for i in basket.items}
    pool = [
        p for p in optimisable_products(db)
        if p.id != original.id and (original.id, p.id) not in rejected and p.id not in in_basket
        and (p.substitution_group == original.substitution_group or p.category == original.category)
    ]
    screened = ctx.compliance.screen(pool, restrictions, household_id=household.id, session_id=session.id) if pool else {}
    compliant = [p for p in pool if screened[p.id].status == ItemCompliance.compliant]
    offers = ctx.analyst.offers(compliant)

    other_total = sum(i.line_total for i in basket.items if i.id != item.id and not i.withheld)
    budget = basket.budget
    viable = [o for o in offers if budget is None or other_total + o.price * item.quantity <= budget + 1e-6]
    if reason in (SubReason.cheaper, SubReason.over_budget):
        viable = [o for o in viable if o.price < item.pack_price]

    if not viable:
        sub.status = SubStatus.discarded
        sub.trade_off = f"No suitable substitute for {original.name} fits your dietary rules and budget."
        name = original.name
        if reason != SubReason.user_requested:
            _remove_item(basket, item, f"{name} was removed — no suitable substitute was available.")
        agent.log("propose_substitution", f"No viable substitute for {name}", session_id=session.id, basket_id=basket.id)
        db.flush()
        return sub

    # Select: same group first, then most shared tags (closest in kind), then cheapest per serving.
    def rank(o):
        return (o.product.substitution_group != original.substitution_group,
                -len(product_tokens(o.product) & product_tokens(original)),
                o.price_per_serving)

    best = sorted(viable, key=rank)[0]
    saving = round((item.pack_price - best.price) * item.quantity, 2)
    notes = _tradeoff_notes(original, best.product, restrictions)
    result = agent.think("tradeoff", {"original": original.name, "replacement": best.product.name, "saving": saving, "notes": notes,
                                       "retailer": best.retailer.name, "quantity": item.quantity})
    sub.replacement_product_id = best.product.id
    sub.replacement_retailer_id = best.retailer.id
    sub.replacement_price = best.price
    sub.trade_off = result.data
    sub.facts = {"saving": saving, "notes": notes, "retailer": best.retailer.name, "quote_id": best.quote_id,
                 "unit_price": best.unit_price, "unit_basis": best.unit_basis}
    db.flush()
    agent.log("propose_substitution", f"{original.name} → {best.product.name} (saves ${saving:.2f})",
              rationale=result.data, session_id=session.id, basket_id=basket.id, llm=result)
    return sub


def accept(agent, sub: Substitution) -> Basket:
    if sub.status != SubStatus.pending or sub.replacement_product_id is None:
        raise SubstitutionError("This substitution is no longer pending.")
    db = agent.db
    item = db.get(BasketItem, sub.basket_item_id)
    if item is None:
        raise SubstitutionError("The basket item no longer exists.")
    replacement = db.get(Product, sub.replacement_product_id)
    item.product_id, item.retailer_id = replacement.id, sub.replacement_retailer_id
    item.quote_id = sub.facts.get("quote_id")
    item.pack_price = sub.replacement_price
    item.rationale = f"Substituted for {sub.original.name}: {sub.trade_off}"
    item.compliance = ItemCompliance.compliant
    item.withheld = False
    item.subtotal()
    db.flush()
    db.refresh(item)
    sub.accept()
    basket = item.basket
    basket.recalc_total()
    _refresh_nutrition(agent, basket)
    agent.log("accept_substitution", f"Accepted: {sub.original.name} → {replacement.name}", basket_id=basket.id, session_id=sub.session_id)
    return basket


def reject(agent, sub: Substitution) -> Basket:
    """Record the declined swap. Per Activity 7.2, a system-flagged item (out of stock /
    failed review) is then removed; a shopper-requested swap leaves the original in place."""
    if sub.status != SubStatus.pending:
        raise SubstitutionError("This substitution is no longer pending.")
    db = agent.db
    from app.domain import ShoppingSession

    session = db.get(ShoppingSession, sub.session_id)
    session.rejected_swaps = list(session.rejected_swaps) + [[sub.original_product_id, sub.replacement_product_id]]
    sub.reject()
    item = db.get(BasketItem, sub.basket_item_id)
    basket = item.basket
    if sub.reason in (SubReason.out_of_stock, SubReason.failed_review):
        _remove_item(basket, item, f"{item.product.name} was removed from your basket.")
    agent.log("reject_substitution", f"Declined: {sub.original.name} → {sub.replacement.name if sub.replacement else '—'}",
              basket_id=basket.id, session_id=session.id)
    return basket


def _remove_item(basket: Basket, item: BasketItem, notice: str) -> None:
    if basket.status == BasketStatus.accepted:
        basket.status = BasketStatus.verified
    basket.items.remove(item)
    basket.recalc_total()
    notes = dict(basket.notes or {})
    notes["notifications"] = list(notes.get("notifications", [])) + [notice]
    basket.notes = notes


def _refresh_nutrition(agent, basket: Basket) -> None:
    from app.optimisation.types import Requirements

    if basket.status == BasketStatus.accepted:
        basket.status = BasketStatus.verified
    notes = dict(basket.notes or {})
    if "requirements" in notes:
        fields = Requirements.__dataclass_fields__
        req = Requirements(**{k: v for k, v in notes["requirements"].items() if k in fields})
        notes["nutrition"] = agent.ctx.compliance.assess_nutrition(basket, req)
        basket.notes = notes


def _tradeoff_notes(original: Product, replacement: Product, restrictions: list[dict]) -> list[str]:
    notes = []
    on, rn = original.nutrition, replacement.nutrition
    for key, label in (("protein_g", "protein"), ("fibre_g", "fibre"), ("fat_g", "fat")):
        a, b = on.get(key, 0) / max(original.servings, 1), rn.get(key, 0) / max(replacement.servings, 1)
        if a and abs(b - a) / a > 0.2:
            notes.append(f"{'more' if b > a else 'less'} {label} per serving ({b:.0f} g vs {a:.0f} g)")
    if abs(replacement.servings - original.servings) >= 1:
        notes.append(f"{replacement.servings:g} servings per pack instead of {original.servings:g}")
    restricted_tags = {t for r in restrictions for t in RESTRICTION_RULES.get(r["restriction"], {}).get("violating_tags", set())}
    contains = {t for ing in replacement.ingredients for t in ing.tags} - restricted_tags
    allergens = contains & {"milk", "egg", "peanuts", "tree_nuts", "soy", "gluten", "fish", "shellfish", "sesame"}
    if allergens:
        notes.append("contains " + ", ".join(sorted(a.replace("_", " ") for a in allergens)) + " (not restricted for your household)")
    return notes
