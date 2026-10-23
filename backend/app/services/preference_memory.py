"""1.2.12 — Taste & preference memory: the rules for remembered preferences.
Owner: Compliance & Preferences.

A remembered preference is soft, and mandatory restrictions always come first:

  - dislike / avoid_brand: matching products are left out of later baskets and repair
    suggestions. Matching uses the same token rule as `catalogue.disliked_by`, so what the
    shopper is shown is exactly what the basket builder applies.
  - like / brand: matching products get the optimiser's `prefer` nudge, so they win a close
    call but never break the budget or the meal targets. Only products screened compliant
    qualify: a liked product that breaks a restriction, or can't be confirmed safe, is never
    pulled in. A dislike beats a like, because disliked products are removed first.
  - A preference never stands in for a restriction: it only matches product names, while a
    restriction is checked through every ingredient (1.2.10).

Saved preferences reach a session when its request is drafted (`intake._apply_household`) and
are frozen into the confirmed constraint set, so a change applies from the next request on.
"""

from __future__ import annotations

from app.domain import Preference, Product
from app.services.catalogue import disliked_by, match_score
from app.services.dietary_rules import RESTRICTION_RULES, label, normalise_restriction

KINDS: dict[str, dict] = {
    "dislike": {"label": "Dislike", "effect": "avoid", "opposite": "like"},
    "like": {"label": "Like", "effect": "favour", "opposite": "dislike"},
    "brand": {"label": "Preferred brand", "effect": "favour", "opposite": "avoid_brand"},
    "avoid_brand": {"label": "Avoid brand", "effect": "avoid", "opposite": "brand"},
}


class PreferenceConflict(ValueError):
    pass


def normalise_value(value: str) -> str:
    """Trimmed, single-spaced, lower case: ' Button  Mushrooms' and 'button mushrooms' are one preference."""
    return " ".join(value.split()).lower()


def as_constraint(kind: str, value: str) -> str:
    """The form a preference takes in a session's constraints ("dislike:mushroom")."""
    return f"{kind}:{value}"


def matches(product: Product, kind: str, value: str) -> bool:
    """Whether a preference is about this product. Avoiding uses the builder's rule (any word of
    the value); favouring needs every word, so 'smoked salmon' doesn't favour all salmon."""
    if KINDS[kind]["effect"] == "avoid":
        return disliked_by(product, [as_constraint(kind, value)]) is not None
    return match_score(product, value) >= 1.0


def favoured_by(product: Product, preferences: list[str]) -> str | None:
    """Why a like or preferred brand from a session's constraints favours this product, if one does."""
    for pref in preferences:
        kind, _, value = pref.partition(":")
        if KINDS.get(kind, {}).get("effect") == "favour" and value and matches(product, kind, value):
            return f"you like {value}" if kind == "like" else f"your preferred brand ({value})"
    return None


def kind_label(kind: str) -> str:
    return KINDS.get(kind, {"label": kind.replace("_", " ")})["label"].lower()


def find_conflict(stored: list[Preference], kind: str, value: str, *, ignore: int | None = None) -> Preference | None:
    """The stored preference that already says this (returned) or its opposite (raised), if any."""
    for p in stored:
        if p.id == ignore or p.value != value:
            continue
        if p.kind == KINDS[kind]["opposite"]:
            raise PreferenceConflict(
                f"You've already saved \"{kind_label(p.kind)}: {value}\". Change or forget that one instead."
            )
        if p.kind == kind:
            return p
    return None


def restriction_hint(kind: str, value: str, household_restrictions: set[str]) -> str | None:
    """A dislike that names an allergen or diet the household hasn't recorded as a restriction."""
    rid = normalise_restriction(value)
    if KINDS.get(kind, {}).get("effect") != "avoid" or rid not in RESTRICTION_RULES or rid in household_restrictions:
        return None
    return (
        f"{label(rid)} looks like an allergy or diet. A preference only matches product names; "
        "add it to a member's restrictions to have every ingredient checked."
    )
