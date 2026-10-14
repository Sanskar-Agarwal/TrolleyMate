"""Domain model, organised by the Stage 1 package diagram (Figure 10).

Domain
├── household_profiles     Shopper (User), Household, HouseholdMember, DietaryProfile, Preference
├── requests_constraints   ShoppingSession, ShoppingRequest, ConstraintSet, Constraint subtypes
├── basket_products        Basket, BasketItem, Product, Ingredient, Substitution, MealPlan
├── pricing                Retailer, PriceQuote
└── safety_audit           ComplianceVerdict, EscalationCase, AuditRecord
"""

from app.domain.basket_products import Basket, BasketItem, Ingredient, MealPlan, Product, Substitution
from app.domain.household_profiles import DietaryProfile, Household, HouseholdMember, Preference, User
from app.domain.pricing import PriceQuote, Retailer
from app.domain.requests_constraints import ConstraintSetRecord, ShoppingRequest, ShoppingSession
from app.domain.safety_audit import AuditRecord, ComplianceVerdict, EscalationCase

__all__ = [
    "AuditRecord",
    "Basket",
    "BasketItem",
    "ComplianceVerdict",
    "ConstraintSetRecord",
    "DietaryProfile",
    "EscalationCase",
    "Household",
    "HouseholdMember",
    "Ingredient",
    "MealPlan",
    "Preference",
    "PriceQuote",
    "Product",
    "Retailer",
    "ShoppingRequest",
    "ShoppingSession",
    "Substitution",
    "User",
]
