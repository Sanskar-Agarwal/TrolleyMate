"""UC-03 — Infeasibility negotiation ("Stretch my budget", 1.2.4). Owner: Negotiation & Substitution.

When no basket fits, work out (a) the minimum budget that satisfies everything
else, and (b) the most days the current budget can cover. The shopper picks one
(or types their own numbers) and the basket is rebuilt. Dietary rules are never
offered as a trade-off.
"""

from __future__ import annotations

import math

from app.domain import ShoppingSession
from app.domain.requests_constraints import ConstraintSet
from app.optimisation import BasketOptimiser, Requirements
from app.optimisation.strategies import LowestCost, OptimisationStrategy
from app.optimisation.types import Candidate
from app.services.session_state import active_constraints


class NegotiationError(ValueError):
    pass


def analyse(agent, session: ShoppingSession, cs: ConstraintSet, req: Requirements, strategy: OptimisationStrategy,
            candidates: list[Candidate], solver_message: str = "") -> dict:
    optimiser = BasketOptimiser()
    cheapest = optimiser.solve(req, LowestCost(), candidates, enforce_budget=False)
    options: list[dict] = []
    blocked: list[str] = []

    if not cheapest.feasible:
        roles = {"protein": req.protein_servings, "carb": req.carb_servings, "veg": req.veg_serves}
        blocked = [role for role, need in roles.items() if need > 0 and not any(c.role == role for c in candidates)]
        if not blocked:
            blocked = ["protein or vegetable"]
    else:
        min_budget = math.ceil(cheapest.total * 100) / 100
        if req.budget is not None and min_budget > req.budget:
            options.append({
                "id": "increase_budget",
                "label": f"Increase budget to ${min_budget:.2f}",
                "detail": f"+${min_budget - req.budget:.2f}, everything else unchanged",
                "budget": min_budget,
            })
        for days in range(req.days - 1, 0, -1):
            smaller = Requirements.from_constraints(cs, days=days)
            if optimiser.solve(smaller, strategy, candidates).feasible:
                meals = int(round(days * req.meals_per_day))
                options.append({
                    "id": "reduce_days",
                    "label": f"Cover {days} day{'s' if days != 1 else ''} instead of {req.days}",
                    "detail": f"{meals} meals per person within ${req.budget:.2f}",
                    "days": days,
                })
                break

    extra = next((o["budget"] - req.budget for o in options if o["id"] == "increase_budget"), None)
    max_days = next((o["days"] for o in options if o["id"] == "reduce_days"), None)
    message = agent.think(
        "negotiation_message",
        {
            "budget": req.budget or 0, "requested_meals": req.person_meals, "blocked_roles": blocked,
            "min_budget": next((o["budget"] for o in options if o["id"] == "increase_budget"), None),
            "extra_needed": extra,
            "max_meals": int(round(max_days * req.meals_per_day * req.household_size)) if max_days else None,
        },
    )
    agent.log(
        "infeasibility_negotiation",
        f"Infeasible at ${req.budget}: {len(options)} option(s) offered",
        rationale=solver_message, session_id=session.id, llm=message, payload={"options": options, "blocked": blocked},
    )
    return {
        "message": message.data,
        "options": options,
        "blocked_roles": blocked,
        "budget": req.budget,
        "days": req.days,
        "person_meals": req.person_meals,
        "shortfall": round(extra, 2) if extra is not None else None,
    }


def apply(agent, session: ShoppingSession, *, option_id: str | None = None, budget: float | None = None,
          days: int | None = None, goal: str | None = None):
    """Accept an offered option, or custom numbers, then rebuild (UC-03 step 4)."""
    from app.workflows import basket_builder

    record = active_constraints(agent.db, session)
    if record is None:
        raise NegotiationError("There are no confirmed constraints to adjust.")
    payload = dict(record.payload)
    if option_id and budget is None and days is None:
        raise NegotiationError("Pass the option's budget or days along with its id.")
    if budget is not None:
        if budget <= 0:
            raise NegotiationError("Budget must be positive.")
        payload["budget"] = round(float(budget), 2)
    if days is not None:
        if days < 1:
            raise NegotiationError("Days must be at least 1.")
        payload["days"] = int(days)
    agent.log("accept_tradeoff", f"Shopper chose: budget ${payload.get('budget')}, {payload.get('days')} days", session_id=session.id)
    return basket_builder.build(agent, session, goal, payload_override=payload, origin="negotiation")
