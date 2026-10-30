# Interface contracts — shopping, permissions, audit and review

Agreed with the area owners in sprint 1 (KAN-25). Serializers live in
`backend/app/api/common.py`; TypeScript mirrors are in `frontend/src/api/types.ts`. Change both
in the same pull request.

Current behavior checked against main `947a59c` on 29 October 2026. All routes below use
the `/api` prefix. FastAPI's `/docs` is the complete request-schema reference.

## Permission matrix

| Resource | Shopper | Dietitian | Founder |
|---|---|---|---|
| Own household, members, preferences | read / write | — (no household) | — (no household) |
| Own sessions, baskets, explanations | read / write | — (no shopper session) | see founder access below |
| Other shoppers' sessions and baskets | 404 | 404 | read / write through the shared ownership helper |
| Review queue (`/escalations`) | 403 | own + unassigned cases | all cases, can assign |
| Review case detail (`/escalations/{id}`) | 403 | read any case by id | read any case |
| Begin / request info / resolve a case | 403 | only when assigned to them | any case (fallback reviewer) |
| Accept a nutrition exception | own basket only | 404 for another shopper's basket | 403 for another shopper's basket |
| Audit log (`/audit`) | own sessions, no payload | empty list with the seeded account | everything, incl. raw prompts |
| Audit stats (`/audit/stats`) | 403 | 403 | read |

Protected routes return **401** without a valid token. Health, model status, goal and dietary
vocabulary routes, plus registration/login, are public. Session and basket ownership failures
return **404**. Staff have no household in the seed data, so `/households/me` returns 404 for
those accounts; household access is based on the account's linked household.

Founder access is an explicit bypass in `own_session`, inherited by basket and chat routes;
it is not a read-only permission. The nutrition-exception endpoint adds a separate shopper-id
check. Reviewer role checks and case-assignment checks govern review actions independently.

## Build and negotiation

`POST /sessions/{id}/basket` accepts `goal` and an optional UUID `operation_id`.
`POST /sessions/{id}/negotiate` accepts the chosen `option_id`, `budget` and/or `days`, an
optional `goal`, and the same optional operation token. The client creates a new token for
each attempt. Both return one of these bodies, with `trace`:

| `status` | Additional fields | Meaning |
|---|---|---|
| `ok` | `basket` | A candidate was committed; inspect its status and withheld items before acceptance. |
| `infeasible` | `negotiation` | No basket fits; review the computed trade-offs. |
| `retryable` | `reason: timeout \| solver_error`, `message` | Search did not produce a verified candidate; keep existing basket and choices. |
| `cancelled` | `message`, empty `trace` | Request transaction rolled back, preserving the previous basket and constraints. |

`POST /sessions/{id}/basket-builds/{operation_id}/cancel` returns `cancellation_requested`
or `already_finished` with `outcome: committed | cancelled | failed`, plus an empty `trace`.
An acknowledgement is not completion: the UI stays busy until the original build returns.
The final cancellation check and commit share a lock, so a completed commit cannot be reported
as cancelled. A pre-start cancellation also prevents that token's later build from doing work.
Duplicate or concurrent builds for the same session return **409**.

This registry is process-local: one API worker, 1,024 recent operations, 20-minute retention
with active builds retained until completion. Cancellation waits for the current solver/provider
call. Receipts are not durable across restart or expiry; closing a tab does not cancel a build.
See [optimisation details](OPTIMISATION_AND_MEALS.md).

## Meal plan

`POST /baskets/{id}/meal-plan` returns `{meal_plan, trace}`; `GET` on the same route returns
the latest current plan or **404**. Generation requires an accepted basket under the active
constraint set, with every item compliant and no withheld items. It rechecks current household
restrictions before planning.

The plan includes `days`, `requested`, `planned`, `missing`, `goal`, `total_minutes`,
`portions_per_meal`, `reused`, `leftovers`, `expired_unused`, `perishable_first`,
`assumed_at_home` and `suggested_additions`. Planned meals carry `ingredients` with actual
allocated `{name, servings}` quantities, alongside `uses`, `optional`, `minutes` and household
headcount `servings`. Adult-equivalent portions control ingredient consumption. Required
ingredients are reserved before optional extras; partial packs can combine without double counting.
Missing meals remain explicit, and suggested additions never change the basket automatically.
Stored plans are hidden when the basket snapshot or active constraints no longer match.

## Household (`GET /api/households/me`)

```json
{
  "id": 1, "name": "Chen–Taylor household", "region": "Sydney Metro", "size": 2,
  "members": [
    {"id": 1, "name": "Alex", "age_group": "adult",
     "restrictions": [{"id": 1, "restriction": "lactose", "kind": "intolerance", "severity": "moderate"}]}
  ],
  "preferences": [{"id": 1, "kind": "dislike", "value": "mushroom", "source": "user"}],
  "mandatory_restrictions": [
    {"restriction": "tree_nuts", "severity": "severe", "kind": "allergy", "source": "household", "members": ["Jamie"]}
  ]
}
```

- `restriction` ids come from `GET /api/dietary/restrictions`; anything else is rejected (400).
- `severity`: `severe` (allergy) · `moderate` (intolerance or diet) · `mild` · `preference` (soft, never mandatory).
- `mandatory_restrictions` is the union across members, keeping the strictest severity
  (UC-10 extension 3a). It is merged into every new shopping request and can't be removed there.
- A rejected save changes nothing: the previous profile is returned by the next `GET`.

## Audit record (`GET /api/audit`)

```json
{
  "id": 42, "timestamp": "2026-10-20T14:03:11", "agent": "AI Nutrition & Compliance",
  "action": "verify_basket", "decision": "Verdict escalated: 0 violation(s), 1 uncertain",
  "rationale": "Ingredient list missing from the retailer feed", "confidence": 0.4,
  "model_version": "deterministic", "provider": "deterministic",
  "session_id": 3, "basket_id": 7,
  "payload": {"llm": {"provider": "...", "model": "...", "fell_back": false, "prompt": {}, "raw": "..."}}
}
```

- Written only through `TechnicalManagerAgent.record` — agents never write audit rows directly.
- `payload` is returned to the founder only.
- `model_version` ends in ` (fallback)` when a real provider failed and the offline mock answered.

## Review case (`GET /api/escalations/{id}`)

```json
{
  "id": 1, "status": "assigned", "product": "Value Chicken Schnitzel 1kg",
  "reason": "Ingredient list missing from the retailer feed", "resolution": null,
  "assigned_to": "Dr Sam Patel", "basket_id": 7, "basket_item_id": 31, "household_id": 1,
  "requirements": [{"restriction": "tree_nuts", "severity": "severe", "label": "Tree nuts"}],
  "evidence": {"confidence": 0.4, "findings": [{"kind": "missing_data", "detail": "..."}], "household": "..."},
  "thread": [{"from": "reviewer", "author": "Dr Sam Patel", "text": "...", "at": "..."}],
  "product_detail": {"ingredients": [], "may_contain": [], "data_complete": false},
  "is_open": true
}
```

- `status` follows State machine 9.5: `open → assigned → under_review ⇄ awaiting_information → resolved`.
- Reading the review queue sweeps assignments not started within `REVIEW_SLA_MINUTES`:
  they return to `open`, then assignment is retried with a different available reviewer.
- `resolution` is `passed` or `failed`. It's applied to the withheld item and reused for the
  same product and household only while it covers every current restriction at the same or a
  stricter severity. The current reuse key does not version the product's ingredient record.
