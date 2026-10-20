"""Demo data loader.

    python -m app.seed            # create tables and load demo data if the DB is empty
    python -m app.seed --reset    # drop everything and reload

Demo accounts (password for all: demo1234)
    alex@trolleymate.demo    Shopper — household with a lactose intolerance and a tree-nut allergy
    riley@trolleymate.demo   Shopper — single person, no restrictions
    sam@trolleymate.demo     Dietitian (authorised reviewer)
    maya@trolleymate.demo    Founder / system administrator
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.domain import (
    DietaryProfile,
    Household,
    HouseholdMember,
    Ingredient,
    Preference,
    PriceQuote,
    Product,
    Retailer,
    User,
)
from app.domain.enums import QuoteSource, QuoteStatus, RestrictionKind, Severity, UserRole
from app.services.pricing.normalisation import normalise
from app.services.pricing.price_sources import retailer_price

SEED_DIR = Path(__file__).resolve().parent
DEMO_PASSWORD = "demo1234"
HISTORY_WEEKS = 8
# Quotes from this retailer are left a day old so the demo can show a stale-price refresh.
STALE_RETAILER = "FreshCo"


def load_catalogue() -> dict:
    return json.loads((SEED_DIR / "catalogue.json").read_text(encoding="utf-8"))


def load_recipes() -> list[dict]:
    return json.loads((SEED_DIR / "recipes.json").read_text(encoding="utf-8"))["recipes"]


def seed_if_empty(db: Session) -> bool:
    if db.scalar(select(User.id).limit(1)) is not None:
        return False
    seed_all(db)
    return True


def seed_all(db: Session) -> None:
    catalogue = load_catalogue()
    _seed_users(db)
    retailers = _seed_retailers(db, catalogue)
    products = _seed_products(db, catalogue)
    _seed_prices(db, catalogue, products, retailers)
    db.commit()


def _seed_users(db: Session) -> None:
    pw = hash_password(DEMO_PASSWORD)
    alex = User(email="alex@trolleymate.demo", display_name="Alex Chen", role=UserRole.shopper, password_hash=pw)
    home = Household(name="Chen–Taylor household", shopper=alex)
    a = HouseholdMember(name="Alex", age_group="adult")
    a.dietary_profiles.append(DietaryProfile(restriction="lactose", kind=RestrictionKind.intolerance, severity=Severity.moderate))
    j = HouseholdMember(name="Jamie", age_group="adult")
    j.dietary_profiles.append(DietaryProfile(restriction="tree_nuts", kind=RestrictionKind.allergy, severity=Severity.severe))
    home.add_member(a)
    home.add_member(j)
    home.preferences.append(Preference(kind="dislike", value="mushroom"))

    riley = User(email="riley@trolleymate.demo", display_name="Riley Brooks", role=UserRole.shopper, password_hash=pw)
    solo = Household(name="Riley's place", shopper=riley)
    solo.add_member(HouseholdMember(name="Riley", age_group="adult"))

    sam = User(
        email="sam@trolleymate.demo", display_name="Dr Sam Patel", role=UserRole.dietitian, password_hash=pw,
        registration_no="DEMO-RD-01", specialisation="Food allergies",
    )
    maya = User(email="maya@trolleymate.demo", display_name="Maya Okafor", role=UserRole.founder, password_hash=pw)
    db.add_all([alex, home, riley, solo, sam, maya])
    db.flush()


def _seed_retailers(db: Session, catalogue: dict) -> dict[str, Retailer]:
    out = {}
    for r in catalogue["retailers"]:
        retailer = Retailer(name=r["name"], region=r["region"], source=r["source"])
        db.add(retailer)
        out[r["name"]] = retailer
    db.flush()
    return out


def _seed_products(db: Session, catalogue: dict) -> dict[str, tuple[Product, dict]]:
    ingredients: dict[str, Ingredient] = {}
    for entry in catalogue["ingredients"]:
        ing = Ingredient(name=entry["name"], tags=entry.get("tags", []), ambiguous=entry.get("ambiguous", False))
        ingredients[entry["name"]] = ing
        db.add(ing)
    db.flush()
    for entry in catalogue["ingredients"]:
        for child in entry.get("components", []):
            ingredients[entry["name"]].components.append(ingredients[child])

    products: dict[str, tuple[Product, dict]] = {}
    for entry in catalogue["products"]:
        product = Product(
            sku=entry["sku"], name=entry["name"], brand=entry.get("brand", ""), category=entry["category"],
            pack_size=entry["pack_size"], unit=entry["unit"], servings=entry["servings"],
            nutrition=entry["nutrition"], tags=entry.get("tags", []), may_contain=entry.get("may_contain", []),
            perishable=entry.get("perishable", False), shelf_life_days=entry.get("shelf_life_days", 30),
            prep_minutes_per_serving=entry.get("prep_minutes_per_serving", 5),
            data_complete=entry.get("data_complete", True), substitution_group=entry.get("substitution_group", ""),
        )
        product.ingredients = [ingredients[name] for name in entry.get("ingredients", [])]
        db.add(product)
        products[entry["sku"]] = (product, entry)
    db.flush()
    return products


def _seed_prices(db: Session, catalogue: dict, products: dict, retailers: dict[str, Retailer]) -> None:
    """8 weeks of history per product/retailer, then one current quote.

    Products with a `special` get a discounted quote on the same weekday each
    week — the pattern buy-timing intelligence (1.2.6) looks for.
    """
    now = datetime.now().replace(microsecond=0)
    today = now.date()
    for product, entry in products.values():
        for name, retailer in retailers.items():
            if name in entry.get("unavailable_at", []):
                continue
            regular = retailer_price(product.sku, product.category, entry["base_price"], name)
            special = entry.get("special")
            special_price = (
                retailer_price(product.sku, product.category, special["price"], name, "special") if special else None
            )
            # Current quotes from partner_api retailers simulate a live feed;
            # catalogue-sourced quotes are synthetic seed data (KAN-13).
            current_source = QuoteSource.live if retailer.source == "partner_api" else QuoteSource.synthetic
            history: list[PriceQuote] = []
            for week in range(HISTORY_WEEKS, 0, -1):
                week_start = datetime.combine(today - timedelta(days=today.weekday() + 7 * week), datetime.min.time())
                history.append(_quote(product, retailer, regular, week_start + timedelta(hours=8), False, QuoteSource.recorded))
                if special:
                    day = week_start + timedelta(days=special["weekday"], hours=7)
                    history.append(_quote(product, retailer, special_price, day, True, QuoteSource.recorded))
                    history.append(_quote(product, retailer, regular, day + timedelta(days=1), False, QuoteSource.recorded))

            special_today = bool(special) and special["weekday"] == today.weekday()
            current_price = special_price if special_today else regular
            captured = now - timedelta(hours=30 if name == STALE_RETAILER else 2)
            current = _quote(product, retailer, current_price, captured, special_today, current_source)
            history.sort(key=lambda q: q.captured_at)
            db.add_all(history + [current])
            db.flush()
            for older in history:
                older.supersede(current)
            current.status = QuoteStatus.stale if name == STALE_RETAILER else QuoteStatus.fresh


def _quote(
    product: Product, retailer: Retailer, price: float, at: datetime, on_special: bool,
    source_type: str = QuoteSource.synthetic,
) -> PriceQuote:
    unit = normalise(price, product.pack_size, product.unit)
    return PriceQuote(
        product_id=product.id, retailer_id=retailer.id, price=price,
        unit_price=unit.value if unit else None, unit_basis=unit.basis if unit else "",
        on_special=on_special, captured_at=at, status=QuoteStatus.fresh,
        source_type=source_type,
    )
