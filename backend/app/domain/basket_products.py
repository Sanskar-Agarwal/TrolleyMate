"""Domain::BasketProducts — Basket, BasketItem, Product, Ingredient, Substitution, MealPlan."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.domain.enums import BasketStatus, ItemCompliance, SubStatus

product_ingredients = Table(
    "product_ingredients",
    Base.metadata,
    Column("product_id", ForeignKey("products.id"), primary_key=True),
    Column("ingredient_id", ForeignKey("ingredients.id"), primary_key=True),
)

# Composite ingredients (e.g. "basil pesto" -> pine nuts, parmesan). This is
# what makes allergen checking "cascading" (1.2.10).
ingredient_components = Table(
    "ingredient_components",
    Base.metadata,
    Column("parent_id", ForeignKey("ingredients.id"), primary_key=True),
    Column("child_id", ForeignKey("ingredients.id"), primary_key=True),
)


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    # Restriction tags this ingredient directly carries, e.g. ["milk", "lactose"].
    tags: Mapped[list] = mapped_column(JSON, default=list)
    # True for vague label terms ("natural flavours", "spices") that need judgement.
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)

    components: Mapped[list[Ingredient]] = relationship(
        secondary=ingredient_components,
        primaryjoin=id == ingredient_components.c.parent_id,
        secondaryjoin=id == ingredient_components.c.child_id,
    )

    def contains_allergen(self, tag: str, _seen: set[int] | None = None) -> bool:
        seen = _seen or set()
        if self.id in seen:
            return False
        seen.add(self.id)
        return tag in self.tags or any(c.contains_allergen(tag, seen) for c in self.components)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    brand: Mapped[str] = mapped_column(String(80), default="")
    # protein | carb | veg | dairy | fruit | pantry | snack
    category: Mapped[str] = mapped_column(String(30))
    pack_size: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(10))  # g | ml | each
    servings: Mapped[float] = mapped_column(Float, default=1.0)
    # Per pack: kcal, protein_g, carbs_g, fat_g, fibre_g, veg_serves
    nutrition: Mapped[dict] = mapped_column(JSON, default=dict)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    may_contain: Mapped[list] = mapped_column(JSON, default=list)
    perishable: Mapped[bool] = mapped_column(Boolean, default=False)
    shelf_life_days: Mapped[int] = mapped_column(Integer, default=30)
    prep_minutes_per_serving: Mapped[float] = mapped_column(Float, default=5.0)
    # False when the retailer feed is missing the ingredient list → "uncertain".
    data_complete: Mapped[bool] = mapped_column(Boolean, default=True)
    substitution_group: Mapped[str] = mapped_column(String(40), default="")

    ingredients: Mapped[list[Ingredient]] = relationship(secondary=product_ingredients)


class Basket(Base):
    __tablename__ = "baskets"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("shopping_sessions.id"))
    constraint_set_id: Mapped[int] = mapped_column(ForeignKey("constraint_sets.id"))
    status: Mapped[str] = mapped_column(String(20), default=BasketStatus.optimised)
    goal: Mapped[str] = mapped_column(String(30))
    total: Mapped[float] = mapped_column(Float, default=0.0)
    budget: Mapped[float | None] = mapped_column(Float, default=None)
    # Structured explanation facts + nutrition summary; see agents/technical_manager.py
    notes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    items: Mapped[list[BasketItem]] = relationship(
        back_populates="basket", cascade="all, delete-orphan", order_by="BasketItem.id"
    )

    def add_item(self, item: BasketItem) -> None:
        self.items.append(item)

    def recalc_total(self) -> float:
        self.total = round(sum(i.subtotal() for i in self.items if not i.withheld), 2)
        return self.total


class BasketItem(Base):
    __tablename__ = "basket_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    basket_id: Mapped[int] = mapped_column(ForeignKey("baskets.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    retailer_id: Mapped[int] = mapped_column(ForeignKey("retailers.id"))
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("price_quotes.id"), default=None)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    pack_price: Mapped[float] = mapped_column(Float)
    line_total: Mapped[float] = mapped_column(Float)
    compliance: Mapped[str] = mapped_column(String(20), default=ItemCompliance.unchecked)
    # Withheld items await human review and are excluded from the total (UC-02 ext 2a).
    withheld: Mapped[bool] = mapped_column(Boolean, default=False)
    rationale: Mapped[str] = mapped_column(Text, default="")

    basket: Mapped[Basket] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()
    retailer: Mapped[Retailer] = relationship()  # noqa: F821

    def subtotal(self) -> float:
        self.line_total = round(self.pack_price * self.quantity, 2)
        return self.line_total


class Substitution(Base):
    __tablename__ = "substitutions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("shopping_sessions.id"))
    basket_item_id: Mapped[int] = mapped_column(ForeignKey("basket_items.id"))
    original_product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    replacement_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), default=None)
    replacement_retailer_id: Mapped[int | None] = mapped_column(ForeignKey("retailers.id"), default=None)
    replacement_price: Mapped[float | None] = mapped_column(Float, default=None)
    reason: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default=SubStatus.pending)
    trade_off: Mapped[str] = mapped_column(Text, default="")
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    original: Mapped[Product] = relationship(foreign_keys=[original_product_id])
    replacement: Mapped[Product | None] = relationship(foreign_keys=[replacement_product_id])

    def accept(self) -> None:
        self.status = SubStatus.accepted

    def reject(self) -> None:
        self.status = SubStatus.rejected


class MealPlan(Base):
    __tablename__ = "meal_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    basket_id: Mapped[int] = mapped_column(ForeignKey("baskets.id"))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
