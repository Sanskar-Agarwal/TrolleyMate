"""Every router is registered here once, so feature work never needs to touch main.py."""

from fastapi import APIRouter

from app.api import (
    audit,
    auth,
    baskets,
    compliance,
    editing,
    escalations,
    households,
    intake,
    meal_plans,
    preferences,
    pricing,
    sessions,
    substitutions,
    system,
)

api_router = APIRouter(prefix="/api")
for module in (
    system, auth, households, preferences, sessions, intake, baskets, substitutions,
    meal_plans, pricing, editing, compliance, escalations, audit,
):
    api_router.include_router(module.router)
