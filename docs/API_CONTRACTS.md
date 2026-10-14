# Interface contracts — households, permissions, audit, review cases

Agreed with the area owners in sprint 1 (KAN-25). Serializers live in
`backend/app/api/common.py`; TypeScript mirrors are in `frontend/src/api/types.ts`. Change both
in the same pull request.

## Permission matrix

| Resource | Shopper | Dietitian | Founder |
|---|---|---|---|
| Own household, members, preferences | read / write | — (no household) | — (no household) |
| Own sessions, baskets, explanations | read / write | — | read |
| Other shoppers' sessions and baskets | 404 | 404 | read |
| Review queue (`/escalations`) | 403 | own + unassigned cases | all cases, can assign |
| Begin / request info / resolve a case | 403 | only when assigned to them | any case (fallback reviewer) |
| Audit log (`/audit`) | own sessions, no payload | none | everything, incl. raw prompts |
| Audit stats (`/audit/stats`) | 403 | 403 | read |

Unauthenticated requests get **401**. Records that exist but belong to someone else return
**404** rather than 403, so ids can't be probed.

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
- An assignment that isn't started within `REVIEW_SLA_MINUTES` returns to `open`.
- `resolution` is `passed` or `failed`. It's applied to the withheld item and reused for the
  same product and household only while it covers every current restriction.
