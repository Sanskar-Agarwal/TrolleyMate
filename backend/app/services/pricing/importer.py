"""Load recorded retailer prices from a CSV or JSON file (1.2.7). Owner: Pricing & Editing.

    python -m app.services.pricing.importer prices.csv        # or prices.json (a list of rows)

Each row: retailer, sku, price, and optionally on_special (true/false) and captured_at (ISO time,
default now). Rows are tagged `recorded` and never overwrite history: a newer price becomes the
current quote and supersedes the old one; an older one is kept as history. Bad rows are reported,
not guessed at.
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import PriceQuote, Product, Retailer
from app.domain.enums import QuoteSource, QuoteStatus
from app.services.pricing.normalisation import normalise


@dataclass
class ImportReport:
    imported: int = 0
    became_current: int = 0
    not_normalised: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


def read_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("A JSON price file must be a list of rows.")
        return rows
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _flag(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def import_quotes(db: Session, rows: list[dict]) -> ImportReport:
    report = ImportReport()
    retailers = {r.name.lower(): r for r in db.scalars(select(Retailer))}
    for n, row in enumerate(rows, start=1):
        label = f"row {n}"
        retailer = retailers.get(str(row.get("retailer", "")).strip().lower())
        product = db.scalar(select(Product).where(Product.sku == str(row.get("sku", "")).strip()))
        try:
            price = round(float(row.get("price")), 2)
            captured = datetime.fromisoformat(str(row["captured_at"]).strip()) if row.get("captured_at") else datetime.now()
        except (TypeError, ValueError):
            report.rejected.append(f"{label}: price or captured_at isn't valid")
            continue
        if retailer is None:
            report.rejected.append(f"{label}: unknown retailer {row.get('retailer')!r}")
            continue
        if product is None:
            report.rejected.append(f"{label}: unknown sku {row.get('sku')!r}")
            continue
        if price <= 0:
            report.rejected.append(f"{label}: price must be positive")
            continue

        unit = normalise(price, product.pack_size, product.unit)
        if unit is None:
            report.not_normalised.append(f"{product.sku} at {retailer.name}")
        quote = PriceQuote(
            product_id=product.id, retailer_id=retailer.id, price=price,
            unit_price=unit.value if unit else None, unit_basis=unit.basis if unit else "",
            on_special=_flag(row.get("on_special", "")), captured_at=captured,
            status=QuoteStatus.fresh, source_type=QuoteSource.recorded,
        )
        db.add(quote)
        db.flush()
        current = db.scalar(
            select(PriceQuote)
            .where(PriceQuote.product_id == product.id, PriceQuote.retailer_id == retailer.id,
                   PriceQuote.status != QuoteStatus.superseded, PriceQuote.id != quote.id)
            .order_by(PriceQuote.captured_at.desc())
        )
        if current is None or captured >= current.captured_at:
            if current is not None:
                current.supersede(quote)
            report.became_current += 1
        else:
            quote.status = QuoteStatus.superseded  # older than what we have: history only
        report.imported += 1
    return report


def main(argv: list[str]) -> int:
    from app.core.db import SessionLocal

    if len(argv) != 1:
        print(__doc__)
        return 2
    rows = read_rows(Path(argv[0]))
    with SessionLocal() as db:
        report = import_quotes(db, rows)
        db.commit()
    print(f"Imported {report.imported} price(s); {report.became_current} now current.")
    for line in report.not_normalised:
        print(f"  unit price not normalised: {line}")
    for line in report.rejected:
        print(f"  rejected {line}")
    return 1 if report.rejected else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
