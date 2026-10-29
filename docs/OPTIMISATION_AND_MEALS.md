# KAN-3 and KAN-4: optimisation and meal-planning evidence

Implementation reference checked against main `947a59c` on 29 October 2026. For dated test
results and the latest verified release, see [README verification](../README.md#verification)
and [UAT_2026-10-28.md](UAT_2026-10-28.md). The fixture descriptions below define checks;
they do not imply a new test run whenever this document is read.

The five goals use deterministic integer optimisation. Dietary compliance is screened before solving and verified afterwards. Budget, required food-role quantities, explicit product limits and nutrition minimums remain constraints for every goal. Missing price data and known violations cannot enter the candidate pool. An uncertain item can produce only a pending-review basket, with the item withheld; it cannot be accepted or meal-planned.

## Goal coefficients

The solver minimises the sum of each pack's coefficient times its integer quantity. Define `N = 0.04 × protein_g + 0.08 × fibre_g + 0.5 × veg_serves` using per-pack nutrition; `W = role servings × (1.6 if perishable, otherwise 1)`; and `T = prep minutes per serving × pack servings`. Vegetable role servings use the catalogue's vegetable-serve value. Other role servings use pack servings.

| Goal | Pack coefficient / additional requirement |
| --- | --- |
| Lowest cost | Pack price |
| Best nutrition | `price × (1 − 0.6 × normalised nutrient density)`; density is `N / price`, divided by the candidate pool's maximum. Also raises baseline vegetable minimum by 60% and protein by 10%. |
| Least waste | `W + 0.05 × price` |
| Fastest cook | `T + 0.05 × price` |
| Balanced | `0.55 × normalised price + 0.20 × normalised W + 0.15 × normalised T + 0.10 × (1 − normalised N)` |

Balanced normalisation divides each component by its maximum in the current compliant/uncertain priced candidate pool. Product preferences reduce their coefficient by `0.08 × abs(coefficient) + 0.01`; uncertainty increases it by `0.10 × abs(coefficient) + 0.01`. Neither changes any hard constraint. Variety caps limit concentrated purchases but explicit pinned quantities can exceed those variety caps.

These are catalogue-based proxies, not predictions of actual kitchen waste or globally optimal cooking time. The accepted-basket planner then uses actual recipe durations and ingredient requirements. It reports recipe gaps explicitly; meeting aggregate nutrition and role requirements does not promise that every named recipe will be available.

### Reproducible choice fixture

`backend/tests/test_optimisation_goals.py` uses one required protein serve, a $2.50 budget, and four single-serve products:

| Product | Price | Prep minutes | Perishable | Protein / fibre g |
| --- | ---: | ---: | --- | --- |
| Cheap | $1.00 | 30 | Yes | 10 / 0 |
| Keeps | $1.20 | 15 | No | 10 / 0 |
| Quick | $2.40 | 1 | No | 10 / 0 |
| Nutrients | $1.60 | 20 | No | 100 / 20 |

Expected selections are Cheap for lowest cost, Nutrients for best nutrition, Keeps for least waste, Quick for fastest cook, and Keeps for balanced. A deliberately cheaper noncompliant candidate is excluded for every goal. At $0.50, every goal reports infeasibility. These synthetic values distinguish objectives; they are not nutrition advice.

## Meal planning and household quantities

Only an accepted basket under the currently active constraints can generate a plan. Current dietary restrictions are checked again before generation. A saved plan is hidden when the basket quantities/compliance or active constraints change. The planner does not add products or change pack quantities.

Every required ingredient slot consumes the confirmed adult-equivalent household portions (legacy baskets use headcount). Partial packs can combine to fill a slot, and flexible ingredient slots cannot double-spend a pack needed by a more specific slot. All required meals are allocated before any optional ingredient. The response and UI show actual allocated ingredient servings, household headcount, adult-equivalent portions, planned/requested meal counts, missing ingredients, usable leftovers and stock not scheduled beyond its shelf life.

Child portion factors scale default food quantities. Breakfast and main requirements round up independently so rounding breakfast never removes a child's main-meal portion. Explicit targets labelled **per person per day** use the full household headcount, without applying the child portion factor.

Recipe selection is deterministic and greedy within the requested calendar:

- Fastest cook prioritises the lowest recipe minutes among recipes feasible for that slot.
- Least waste prioritises required perishable servings divided by days remaining until expiry (inclusive).
- Other goals favour opened packs, ingredients near expiry, recipe variety and named recipes, with a small recipe-time penalty. Breakfast favours stock not needed for main meals.
- Ties for the two specialised goals use the same reuse/variety considerations. Cross-meal reuse counts distinct calendar slots, not repeated use within one meal.

`total_minutes` sums the selected recipes' household-batch durations. It does not assume parallel cooking, batch preparation or account for each household's equipment. Salt, pepper and cooking oil are explicitly assumed at home. Suggested missing products are informational and require a separately reviewed basket change.

`backend/tests/test_meal_planning.py` covers combined partial packs, optional-ingredient reservation, fractional child portions, expiry, withheld stock, cross-meal reuse, time/waste recipe selection, acceptance, and stale-plan hiding. The React meal-plan tests cover acceptance gating, distinct meal/ingredient gaps, quantities, estimated cooking time, pantry assumptions and safe repeated generation.

## Incomplete searches and preserving a valid basket

A solver timeout without a valid candidate and an unknown solver failure return `status: retryable` with a reason and retry message. They do not mark a confirmed request infeasible or start constraint negotiation. A time-limited incumbent is usable only after checking the rounded integer quantities against every solver constraint. Proven infeasibility retains the existing negotiation path.

A failed solve leaves the prior basket and active constraints intact. A failed dietary verification raises an error and the request transaction rolls back. The new basket, constraints and superseding state commit together only after presentation succeeds. A pending-review candidate leaves the prior accepted/verified basket preserved in history; an explicitly approved negotiation/edit can still activate its new constraints. Such an older basket may therefore no longer match current constraints. Once a newer verified basket is accepted, older preserved baskets are superseded. Pending candidates cannot be accepted or meal-planned.

Build and negotiation requests accept an optional UUID `operation_id`. The UI generates it before starting work and sends an explicit cancellation request to `POST /sessions/{session_id}/basket-builds/{operation_id}/cancel`. A cancellation acknowledgement means the server received the request; the UI waits for the original build to return `status: cancelled` after rollback before reporting completion. The acknowledgement can arrive before build registration: its token is retained so the later build performs no work.

Cancellation checkpoints run between screening, pricing, each solver pass, verification and explanation. A synchronous solver or LLM call finishes its current pass first. The final check and database commit share a lock: cancellation wins before commit and rolls back every candidate/constraint/audit write, or the cancellation endpoint reports `already_finished` with `outcome: committed`. A second build for the same session receives HTTP 409 while one is active; other sessions have independent operation IDs. Session ownership is checked before any cancellation state is changed.

The current Docker and local server run one API process. The thread-safe operation registry is deliberately process-local, capped at 1,024 recent operations and a 20-minute retention period, with active operations retained until they finish. Operation IDs must be unique for each attempt. Completion receipts are not durable across restarts or beyond retention; a cancellation acknowledgement alone must never be treated as proof that an earlier result was undone. Multiple API worker processes would require a shared job registry before deployment. Closing a browser tab does not automatically request cancellation.

`backend/tests/test_build_cancellation.py` uses concurrent HTTP requests to cancel after candidate persistence, checks rollback of negotiation overrides and the old accepted basket, tests cancellation before registration, rejects another shopper's cancellation, and checks both sides of the commit race and bounded cleanup.

## Targeted verification

From `backend`, with the mock LLM configured, run:

```sh
python -m pytest tests/test_optimisation_goals.py tests/test_meal_planning.py tests/test_basket_constraints.py tests/test_build_cancellation.py
```

From `frontend`, run the focused React tests with:

```sh
npm test -- src/features/mealplan/MealPlanView.test.tsx
```

Full backend, frontend, build and Docker results are linked from [README verification](../README.md#verification).
