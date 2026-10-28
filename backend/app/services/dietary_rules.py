"""Restriction vocabulary shared by intake, profiles and compliance (1.2.10, 1.2.13).

A restriction id (e.g. "vegan") maps to the ingredient tags that violate it.
Ingredient tags are set in the seed catalogue (`seed/catalogue.json`).
"""

RESTRICTION_RULES: dict[str, dict] = {
    "milk": {"label": "Milk / dairy", "kind": "allergy", "violating_tags": {"milk"}},
    "lactose": {"label": "Lactose", "kind": "intolerance", "violating_tags": {"lactose"}},
    "egg": {"label": "Egg", "kind": "allergy", "violating_tags": {"egg"}},
    "peanuts": {"label": "Peanuts", "kind": "allergy", "violating_tags": {"peanuts"}},
    "tree_nuts": {"label": "Tree nuts", "kind": "allergy", "violating_tags": {"tree_nuts"}},
    "soy": {"label": "Soy", "kind": "allergy", "violating_tags": {"soy"}},
    "gluten": {"label": "Gluten (coeliac)", "kind": "allergy", "violating_tags": {"gluten"}},
    "wheat": {"label": "Wheat", "kind": "allergy", "violating_tags": {"wheat"}},
    "fish": {"label": "Fish", "kind": "allergy", "violating_tags": {"fish"}},
    "shellfish": {"label": "Shellfish", "kind": "allergy", "violating_tags": {"shellfish"}},
    "sesame": {"label": "Sesame", "kind": "allergy", "violating_tags": {"sesame"}},
    "vegetarian": {"label": "Vegetarian", "kind": "diet", "violating_tags": {"meat", "fish", "shellfish", "gelatine", "animal_rennet"}},
    "vegan": {
        "label": "Vegan",
        "kind": "diet",
        "violating_tags": {"meat", "fish", "shellfish", "gelatine", "animal_rennet", "milk", "egg", "honey"},
    },
    "halal": {"label": "Halal", "kind": "diet", "violating_tags": {"pork", "alcohol"}},
    "pork_free": {"label": "No pork", "kind": "diet", "violating_tags": {"pork"}},
}

_ALIASES = {
    "dairy": "milk",
    "nuts": "tree_nuts",
    "nut": "tree_nuts",
    "tree_nut": "tree_nuts",
    "peanut": "peanuts",
    "eggs": "egg",
    "coeliac": "gluten",
    "celiac": "gluten",
    "gluten_free": "gluten",
    "lactose_intolerance": "lactose",
    "prawns": "shellfish",
}


def normalise_restriction(value: str) -> str:
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    return _ALIASES.get(key, key)


def violating_tags(restriction: str) -> set[str]:
    rule = RESTRICTION_RULES.get(normalise_restriction(restriction))
    return set(rule["violating_tags"]) if rule else {normalise_restriction(restriction)}


def label(restriction: str) -> str:
    rule = RESTRICTION_RULES.get(normalise_restriction(restriction))
    return rule["label"] if rule else restriction.replace("_", " ").title()
