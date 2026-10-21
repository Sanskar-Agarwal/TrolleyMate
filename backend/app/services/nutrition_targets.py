"""Prototype nutrition targets for the adequacy check (1.2.11). Owner: Compliance & Preferences.

`Requirements.from_constraints` scales these by the meal schedule: energy per person-meal,
protein and vegetables per main meal (breakfasts excluded). A shopper's own protein target
can raise the protein figure, never lower it.

Each target records the published reference it starts from and the demo assumption that turns
a daily reference for one adult into a per-meal figure. Targets cover only the meals the shopper
asks the basket to cover. They are prototype values for the demo, not dietary advice: a dietitian
should confirm them before real use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TARGETS_VERSION = "prototype-2026-10"


@dataclass(frozen=True)
class NutritionTarget:
    nutrient: str
    amount: float
    unit: str
    per: Literal["person_meal", "main_meal"]
    reference: str
    source: str
    assumption: str


TARGETS: dict[str, NutritionTarget] = {
    t.nutrient: t
    for t in (
        NutritionTarget(
            "kcal", 550, "kcal", "person_meal",
            reference="8,700 kJ (about 2,080 kcal) a day, the average adult intake behind %DI on food labels",
            source="FSANZ Australia New Zealand Food Standards Code, Standard 1.2.8",
            assumption="About a quarter of the daily reference per meal; snacks and drinks bought elsewhere make up the rest.",
        ),
        NutritionTarget(
            "protein_g", 22, "g", "main_meal",
            reference="RDI of 64 g a day for men and 46 g for women aged 19-70",
            source="NHMRC Nutrient Reference Values for Australia and New Zealand (2006)",
            assumption="64 g over three meals is about 21 g; rounded up to 22 g per main meal so the higher RDI is met.",
        ),
        NutritionTarget(
            "veg_serves", 2.0, "serves", "main_meal",
            reference="5-6 serves of vegetables a day for adults aged 19-50 (one serve = 75 g)",
            source="NHMRC Australian Dietary Guidelines (2013)",
            assumption="Two serves per main meal; with two main meals a day the basket supplies 4, other meals and snacks the rest.",
        ),
        NutritionTarget(
            "staple_serves", 1.0, "serves", "main_meal",
            reference="6 serves of grain (cereal) foods a day for adults aged 19-50",
            source="NHMRC Australian Dietary Guidelines (2013)",
            assumption="One serving of a grain or starch staple per main meal, counted in each pack's own servings: "
                       "the rule the optimiser already applies (Requirements.carb_servings).",
        ),
    )
}
