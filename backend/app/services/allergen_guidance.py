"""Retrieval over allergen labelling guidance for the Nutrition & Compliance agent (1.2.10).

When a label uses a vague or technical term ("emulsifier (322)", "whey powder", "natural flavours"),
the agent retrieves the notes below that mention the term or the restriction and gives them to the
model alongside the question, so its judgement is grounded in written guidance rather than recall.
The notes are short summaries in our own words of how Australian labels declare allergens under the
FSANZ Food Standards Code (Standard 1.2.3, allergen declarations, and the food-additive numbering
in Standard 1.2.4). They are guidance for screening, not a substitute for the dietitian review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SOURCE = "FSANZ Food Standards Code, Standards 1.2.3 and 1.2.4 (summarised)"


@dataclass(frozen=True)
class Note:
    id: str
    terms: tuple[str, ...]          # label words this note is about
    restrictions: tuple[str, ...]   # restriction ids it bears on
    risk: str                       # likely | possible | none
    text: str


NOTES: tuple[Note, ...] = (
    Note("whey", ("whey", "whey powder", "casein", "caseinate", "milk solids", "ghee", "butter"), ("milk", "lactose", "vegan"),
         "likely", "Whey, casein, caseinates, milk solids, butter and ghee are all made from milk."),
    Note("lactitol", ("lactitol", "966"), ("milk", "lactose"), "likely",
         "Sweetener 966 (lactitol) is made from lactose."),
    Note("lecithin", ("lecithin", "322", "emulsifier (322)"), ("soy", "egg"), "possible",
         "Emulsifier 322 is lecithin, most often from soy and sometimes from egg; the source isn't always named."),
    Note("e471", ("471", "472", "mono- and diglycerides", "emulsifier (471)", "emulsifier (472)"), ("vegan", "vegetarian", "halal", "pork_free"),
         "possible", "Emulsifiers 471 and 472 are made from fats that can be plant or animal (including pork) unless stated."),
    Note("lysozyme", ("lysozyme", "1105"), ("egg",), "likely", "Preservative 1105 (lysozyme) is extracted from egg white."),
    Note("albumin", ("albumin", "albumen", "ovalbumin", "meringue"), ("egg", "vegan"), "likely",
         "Albumin/albumen and meringue come from egg white."),
    Note("gelatine", ("gelatine", "gelatin", "441"), ("vegan", "vegetarian", "halal", "pork_free"), "likely",
         "Gelatine (441) is made from animal collagen, commonly pork or beef."),
    Note("carmine", ("carmine", "cochineal", "120"), ("vegan", "vegetarian"), "likely", "Colour 120 (carmine/cochineal) is made from insects."),
    Note("shellac", ("shellac", "904", "glazing agent (904)"), ("vegan",), "likely", "Glazing agent 904 (shellac) is an insect secretion."),
    Note("bone-phosphate", ("bone phosphate", "542"), ("vegan", "vegetarian", "halal"), "likely", "Food acid 542 (bone phosphate) is made from animal bone."),
    Note("natural-flavours", ("natural flavours", "natural flavour", "flavour"), ("milk", "lactose", "tree_nuts", "peanuts", "vegan"),
         "possible", "'Natural flavour' can be dairy- or nut-derived; declared allergens must still be named, but the base isn't always given."),
    Note("vegetable-oil", ("vegetable oil", "vegetable fat"), ("peanuts", "soy", "sesame"), "possible",
         "Unspecified vegetable oil can include peanut, soy or sesame oil; refined oils are usually low-risk but not guaranteed."),
    Note("spices", ("spices", "seasoning", "spice blend"), ("gluten", "wheat", "sesame", "milk"), "possible",
         "Spice blends and seasonings can carry wheat flour, sesame or milk powder as carriers or anti-caking agents."),
    Note("malt", ("malt", "malt extract", "barley malt"), ("gluten", "wheat"), "likely", "Malt and malt extract are made from barley and contain gluten."),
    Note("semolina", ("semolina", "durum", "spelt", "couscous"), ("gluten", "wheat"), "likely", "Semolina, durum, spelt and couscous are wheat."),
    Note("marzipan", ("marzipan", "frangipane", "praline", "nougat", "gianduja"), ("tree_nuts",), "likely",
         "Marzipan and frangipane are almond; praline, nougat and gianduja are usually hazelnut or almond."),
    Note("pesto", ("pesto",), ("tree_nuts", "milk", "lactose"), "likely", "Pesto usually has pine nuts or cashews and parmesan."),
    Note("tahini", ("tahini", "hummus", "halva"), ("sesame",), "likely", "Tahini is sesame paste; hummus and halva usually contain it."),
    Note("surimi", ("surimi", "fish sauce", "anchovy", "worcestershire"), ("fish",), "likely",
         "Surimi, fish sauce and anchovies are fish; Worcestershire sauce usually has anchovy."),
    Note("curry-paste", ("curry paste", "red curry paste", "green curry paste", "shrimp paste"), ("shellfish", "fish"), "possible",
         "Thai curry pastes often include shrimp paste or fish sauce."),
    Note("soy-sauce", ("soy sauce", "tamari", "miso"), ("soy", "gluten", "wheat"), "likely",
         "Soy sauce is soy and usually wheat; tamari can be wheat-free; miso is soy."),
)

_WORD = re.compile(r"[a-z0-9]+")
# Label words too generic to link a term to a note on their own ("emulsifier (471)" isn't lecithin).
_GENERIC = {"emulsifier", "powder", "oil", "sauce", "paste", "vegetable", "natural", "extract", "agent", "fat", "and"}


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower())) - _GENERIC


def retrieve(ingredient: str, restriction: str, k: int = 3) -> list[Note]:
    """Notes most relevant to this label term and restriction: exact term matches first, then
    word overlap. Only notes that bear on the restriction are returned."""
    term, words = ingredient.lower().strip(), _tokens(ingredient)
    scored = []
    for note in NOTES:
        if restriction not in note.restrictions:
            continue
        exact = any(term == t or t in term for t in note.terms)
        overlap = len(words & set().union(*(_tokens(t) for t in note.terms)))
        if exact or overlap:
            scored.append(((2 if exact else 0) + overlap, note))
    scored.sort(key=lambda s: -s[0])
    return [n for _, n in scored[:k]]
