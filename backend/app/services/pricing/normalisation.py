"""Unit-price normalisation (1.2.7) — deterministic, no LLM.

Converts a pack price into price per 100 g, per 100 mL, or per item so that
different pack sizes can be compared fairly. Returns None when the pack cannot
be normalised; callers must then flag the product instead of comparing it.
"""

from __future__ import annotations

from dataclasses import dataclass

_TO_BASE = {"g": ("g", 1.0), "kg": ("g", 1000.0), "ml": ("ml", 1.0), "l": ("ml", 1000.0), "each": ("each", 1.0)}


@dataclass(frozen=True)
class UnitPrice:
    value: float
    basis: str  # "100g" | "100ml" | "each"

    def label(self) -> str:
        return f"${self.value:.2f} / {'100 g' if self.basis == '100g' else '100 mL' if self.basis == '100ml' else 'each'}"


def normalise(price: float, pack_size: float, unit: str) -> UnitPrice | None:
    if price is None or price <= 0 or pack_size is None or pack_size <= 0:
        return None
    base = _TO_BASE.get((unit or "").lower())
    if base is None:
        return None
    base_unit, factor = base
    quantity = pack_size * factor
    if base_unit == "each":
        return UnitPrice(round(price / quantity, 3), "each")
    return UnitPrice(round(price / quantity * 100, 3), f"100{base_unit}")
