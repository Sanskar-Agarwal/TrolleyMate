"""Catalogue look-ups shared by building, editing and substitution."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import Basket, BasketItem, Product

OPTIMISABLE_CATEGORIES = ("protein", "carb", "veg", "dairy", "fruit")
_STOP = {"the", "a", "an", "some", "of", "with", "and", "pack", "pk", "g", "kg", "ml", "l"}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower().replace("_", " "))
    out = set()
    for w in words:
        if w in _STOP or len(w) < 2:
            continue
        out.add(w)
        if w.endswith("es") and len(w) > 4:
            out.add(w[:-2])
        if w.endswith("s") and len(w) > 3:
            out.add(w[:-1])
    return out


def product_tokens(p: Product) -> set[str]:
    return _tokens(" ".join([p.name, p.brand, p.category, p.substitution_group, *p.tags]))


def match_score(p: Product, text: str) -> float:
    wanted = _tokens(text)
    if not wanted:
        return 0.0
    return len(wanted & product_tokens(p)) / len(wanted)


def optimisable_products(db: Session) -> list[Product]:
    return list(db.scalars(select(Product).where(Product.category.in_(OPTIMISABLE_CATEGORIES)).order_by(Product.id)))


def find_products(db: Session, text: str, limit: int = 5) -> list[Product]:
    scored = [(match_score(p, text), p) for p in db.scalars(select(Product))]
    scored = [sp for sp in scored if sp[0] > 0]
    scored.sort(key=lambda sp: (-sp[0], sp[1].id))
    return [p for _, p in scored[:limit]]


def match_item(basket: Basket, target: str) -> BasketItem | None:
    best, best_score = None, 0.0
    for item in basket.items:
        score = match_score(item.product, target)
        if score > best_score:
            best, best_score = item, score
    return best


def disliked_by(p: Product, preferences: list[str]) -> str | None:
    """Return the preference that rules this product out, if any (soft filter, 1.2.12)."""
    toks = product_tokens(p)
    for pref in preferences:
        kind, _, value = pref.partition(":")
        if kind in ("dislike", "avoid_brand") and value and (_tokens(value) & toks):
            return pref
    return None
