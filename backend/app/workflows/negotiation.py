"""UC-03 — Infeasibility negotiation ("Stretch my budget", 1.2.4). Owner: Negotiation & Substitution.

When no basket fits, work out (a) the minimum budget that satisfies everything
else, and (b) the most days the current budget can cover. The shopper picks one
(or types their own numbers) and the basket is rebuilt only then; a choice that
still doesn't fit leaves the constraints as they were and offers new options.
Cancelling keeps the confirmed constraints unchanged. Dietary rules are never
offered as a trade-off: candidates are screened before the solver, and a choice
can only change the budget, the days or the goal.
"""

from __future__ import annotations

import math

from app.domain import ShoppingSession
from app.domain.requests_constraints import ConstraintSet
from app.optimisation import BasketOptimiser, Requirements
from app.optimisation.strategies import LowestCost, OptimisationStrategy
from app.optimisation.types import Candidate
from app.services.meal_schedule import meal_schedule
from app.services.session_state import active_constraints, latest_basket

OPTION_IDS = ("increase_budget", "reduce_days")


class NegotiationError(ValueError):
    pass


def analyse(agent, session: ShoppingSession, cs: ConstraintSet, req: Requirements, strategy: OptimisationStrategy,
            candidates: list[Candidate], solver_message: str = "", *, min_qty: dict[int, int] | None = None,
            max_qty: dict[int, int] | None = None, reserve: float = 0.0) -> dict:
    """`req` is what the solver was asked for. `reserve` is budget already spent outside the solver
    (chat-edit extras): offered budgets include it. Pins (`min_qty`/`max_qty`) stay in force."""
    optimiser = BasketOptimiser()
    pins = {"min_qty": min_qty, "max_qty": max_qty}
    # Price the goal's own bar (e.g. Best Nutrition asks for more veg), cheapest way, no budget cap.
    cheapest = optimiser.solve(strategy.adjust(req), LowestCost(), candidates, enforce_budget=False, **pins)
    options: list[dict] = []
    blocked: list[str] = []
    timed_out = cheapest.failure_reason is not None  # timeout or solver error: the search didn't finish

    if timed_out:
        pass  # no answer is not proof that nothing fits: offer nothing rather than a wrong number
    elif not cheapest.feasible:
        roles = {"protein": req.protein_servings, "carb": req.carb_servings, "veg": req.veg_serves}
        blocked = [role for role, need in roles.items() if need > 0 and not any(c.role == role for c in candidates)]
        if not blocked:
            blocked = ["protein or vegetable"]
    else:
        budget = None if req.budget is None else round(req.budget + reserve, 2)
        min_budget = math.ceil(round((cheapest.total + reserve) * 100, 6)) / 100
        if budget is not None and min_budget > budget:
            options.append({
                "id": "increase_budget",
                "label": f"Increase budget to ${min_budget:.2f}",
                "detail": f"+${min_budget - budget:.2f}, everything else unchanged",
                "budget": min_budget,
            })
        # Most whole days the current budget covers, everything else (restrictions, pins, goal) unchanged.
        for days in range(req.days - 1, 0, -1):
            smaller = Requirements.from_constraints(cs, days=days, budget=req.budget)
            result = optimiser.solve(smaller, strategy, candidates, **pins)
            timed_out = timed_out or result.failure_reason is not None
            if result.feasible:
                meals = len([m for slots in meal_schedule(days, req.meals_per_day) for m in slots])
                options.append({
                    "id": "reduce_days",
                    "label": f"Cover {days} day{'s' if days != 1 else ''} instead of {req.days}",
                    "detail": f"{meals} meals per person within ${budget:.2f}" if budget is not None else f"{meals} meals per person",
                    "days": days,
                    "person_meals": smaller.person_meals,
                })
                break

    extra = next((o["budget"] - round(req.budget + reserve, 2) for o in options if o["id"] == "increase_budget"), None)
    reduced = next((o for o in options if o["id"] == "reduce_days"), None)
    message = agent.think(
        "negotiation_message",
        {
            "budget": round((req.budget or 0) + reserve, 2), "requested_meals": req.person_meals, "blocked_roles": blocked,
            "min_budget": next((o["budget"] for o in options if o["id"] == "increase_budget"), None),
            "extra_needed": extra,
            "max_meals": reduced["person_meals"] if reduced else None,
            "timed_out": timed_out,
        },
    )
    agent.log(
        "infeasibility_negotiation",
        f"Infeasible at ${req.budget}: {len(options)} option(s) offered",
        rationale=solver_message, session_id=session.id, llm=message,
        payload={"options": options, "blocked": blocked, "timed_out": timed_out},
    )
    return {
        "message": message.data,
        "options": options,
        "blocked_roles": blocked,
        "budget": None if req.budget is None else round(req.budget + reserve, 2),
        "days": req.days,
        "person_meals": req.person_meals,
        "shortfall": round(extra, 2) if extra is not None else None,
        "timed_out": timed_out,  # the search hit the solver time limit, so an option may be missing or not the best
    }


def apply(agent, session: ShoppingSession, *, option_id: str | None = None, budget: float | None = None,
          days: int | None = None, goal: str | None = None):
    """Accept an offered option, or custom numbers, then rebuild (UC-03 step 4)."""
    from app.workflows import basket_builder

    record = active_constraints(agent.db, session)
    if record is None:
        raise NegotiationError("There are no confirmed constraints to adjust.")
    payload = dict(record.payload)  # restrictions, preferences and targets carry over untouched
    if option_id is not None and option_id not in OPTION_IDS:
        raise NegotiationError("Unknown trade-off option.")
    if budget is None and days is None and goal is None:
        raise NegotiationError("Choose a budget, a number of days or a different goal.")
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


def cancel(agent, session: ShoppingSession) -> dict:
    """The shopper declines every trade-off (UC-03 failure scenario). Nothing is re-solved: the confirmed
    constraints, the request's status and any earlier basket stay exactly as they were."""
    record = active_constraints(agent.db, session)
    if record is None:
        raise NegotiationError("There is no negotiation to cancel.")
    basket = latest_basket(agent.db, session.id)
    agent.log("cancel_negotiation", "Shopper declined every trade-off; constraints unchanged",
              rationale=f"Constraint set v{record.version} stays active", session_id=session.id)
    return {"constraint_set_id": record.id, "version": record.version, "basket": basket}
