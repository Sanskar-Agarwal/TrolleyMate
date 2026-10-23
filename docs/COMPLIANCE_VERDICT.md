# Compliance verdict contract (KAN-19, KAN-20, KAN-21, KAN-22)

What the AI Nutrition & Compliance agent returns to the other agents. Covers requirements
1.2.10, 1.2.11 and 1.2.12, UC-06, UC-02 extension 4b (nutrition exceptions), and Stage 1 diagrams 7.4,
8.4 and 9.4.

| | |
|---|---|
| Schema | [`backend/app/services/compliance_verdict.py`](../backend/app/services/compliance_verdict.py) |
| Nutrition targets | [`backend/app/services/nutrition_targets.py`](../backend/app/services/nutrition_targets.py) |
| Preference rules | [`backend/app/services/preference_memory.py`](../backend/app/services/preference_memory.py) |
| Fixture catalogue | [`backend/tests/fixtures/compliance_cases.json`](../backend/tests/fixtures/compliance_cases.json) |
| Tests | [`test_compliance_contract.py`](../backend/tests/test_compliance_contract.py), [`test_compliance_verification.py`](../backend/tests/test_compliance_verification.py), [`test_nutrition_coverage.py`](../backend/tests/test_nutrition_coverage.py), [`test_preference_memory.py`](../backend/tests/test_preference_memory.py), [`PreferencesPanel.test.tsx`](../frontend/src/features/preferences/PreferencesPanel.test.tsx) |

## Verdicts

**Per product** — sequence 8.4, `classifyProduct()`; stored as `BasketItem.compliance`:

| Status | Meaning | Effect |
|---|---|---|
| `compliant` | No restriction conflict found, evidence complete | May enter the basket |
| `violation` | A known conflict with a mandatory restriction | Excluded |
| `uncertain` | Evidence missing, vague or untrustworthy | Withheld; never inserted automatically (UC-06 ext 2a) |

**Per basket** — state machine 9.4 final states; stored as `ComplianceVerdict.status`:

| 9.4 state | Stored status | Rule |
|---|---|---|
| Passed (outcome PASS) | `passed` | Every product compliant |
| Failed (outcome FAIL) | `failed` | Any violation (a violation outranks uncertainty) |
| Uncertain, still unresolved → EscalationRequested (outcome ESCALATED) | `escalated` | No violation, at least one uncertain product |

The stored values are unchanged, so the escalation workflow and API keep working. Automated
verification ends at PASS, FAIL or the escalation request; the human review that follows (9.5) is
outside this contract.

## Evidence (`ComplianceVerdict.evidence`)

```json
{
  "schema_version": 2,
  "restrictions": [{"restriction": "tree_nuts", "severity": "severe", "label": "Tree nuts"}],
  "products": [{
    "product_id": 12, "product": "Basil Pesto 190g", "status": "violation", "confidence": 1.0,
    "findings": [{"kind": "contains", "restriction": "tree_nuts",
                  "ingredient": "basil pesto → pine nuts", "detail": "Contains pine nuts (tree_nuts)"}]
  }],
  "nutrition": { "...": "see below" }
}
```

- `findings[].kind` is one of `contains`, `ambiguous`, `may_contain`, `missing_data`, `data_error`, `human_review`.
  `data_error` marks evidence that can't be trusted (UC-06 failure scenario, 9.4 `dataSourceError`): an
  unreadable ingredient record or may-contain statement, or a composite that contains itself. The product
  is uncertain, so it is withheld and escalated; the readable rest of the record is still checked, so a
  known conflict still fails it.
- `ingredient` is the cascade path through composite ingredients.
- A `violation` or `uncertain` product must carry at least one finding. Unknown keys are rejected,
  so a new piece of evidence has to be added to the schema first.

## Nutrition coverage (1.2.11)

Energy, protein, vegetables and staples are checked against targets already scaled to the
household size and meal schedule (`Requirements.from_constraints`). Withheld items don't count.

- `coverage`: one entry per target, `{nutrient, required, provided, coverage_pct, met, accepted}`
- `gaps`: exactly the unmet targets, each with `short_by`
- `exceptions`: gaps the shopper explicitly accepted (schema version 2, KAN-21)
- `targets`: the target version the requirements were built from (`prototype-2026-10`)

`adequate` is true only when every target is either met or `accepted`. An exception covers its
nutrient only while the current shortfall is no bigger than the one accepted, so a basket that
gets worse needs a fresh decision. Rebuilding the basket starts with no exceptions.

**Candidate repairs:** `GET /api/baskets/{id}/nutrition` returns the current coverage plus up to
three repairs per open gap. A repair is a product not already in the basket, not disliked, and
`compliant` for every mandatory restriction (an `uncertain` product is never suggested), priced at
its cheapest retailer. Each repair says how many packs close the gap (`closes_gap`, capped at 6
packs) and whether it fits the remaining budget. Repairs are suggestions; nothing is added.

**Accepting a gap (UC-02 ext 4b):** `POST /api/baskets/{id}/nutrition/exceptions` with
`{"nutrients": [...], "note": "..."}`. Only the basket's shopper can call it (the founder gets 403),
and only for a current gap (anything else is 400). It records who accepted what, when and why on the
basket, and writes an `accept_nutrition_exception` audit record: the exception trace. It never
changes item compliance: a withheld item stays withheld and the basket can't be accepted until review.

**Basket acceptance gate:** `POST /api/baskets/{id}/accept` also requires every target to be met
or explicitly accepted (400 otherwise, naming the open gaps), and the Accept button is disabled
with the same message. The check runs on the basket as it is now, not on the summary saved when it
was built. That summary goes stale when a dietitian releases or removes an item, or when extras are
added after an edit, so basket reads (`basket_out`) report current nutrition too, and the button and
the server always agree.

## Prototype nutrition targets

Prototype values for the demo, not dietary advice. They match the constants the optimiser already
uses in `Requirements`, and a test keeps the two in step.

| Target | Per | Reference | Source | Demo assumption |
|---|---|---|---|---|
| 550 kcal | person-meal | 8,700 kJ/day average adult intake (%DI) | FSANZ Food Standards Code, Std 1.2.8 | About a quarter of the day per meal; snacks bought elsewhere |
| 22 g protein | main meal | RDI 64 g/day men, 46 g/day women (19–70) | NHMRC Nutrient Reference Values (2006) | 64 g over three meals, rounded up |
| 2 serves veg | main meal | 5–6 serves/day, adults 19–50 (serve = 75 g) | NHMRC Australian Dietary Guidelines (2013) | The basket covers the planned main meals only |
| 1 staple serving | main meal | 6 serves/day of grain (cereal) foods, adults 19–50 | NHMRC Australian Dietary Guidelines (2013) | Counted in each grain/starch pack's own servings, as the optimiser counts them |

Breakfasts add energy but not the main-meal targets. A shopper's own protein target can raise the
protein figure, never lower it.

## Adversarial fixtures

27 cases, each one product screened against a household:

| Category | Cases | Examples |
|---|---|---|
| Hidden ingredients | 8 | whey in crackers, casein under a "dairy-free" label, E471 for a vegan, coconut milk (not dairy) |
| Composite products | 6 | pesto with two allergens, shellfish three levels deep, a composite that contains itself, a shared sub-ingredient (not a cycle) |
| Missing information | 6 | no ingredient list, an empty list marked complete, an unreadable record, precautionary labels |
| Conflicting restrictions | 7 | different severities across members, a request trying to relax the profile, vegan + halal |

One case is specified ahead of the code and runs as a strict xfail until it lands: animal rennet in
parmesan should be a `violation` for vegetarians (knowledge-base growth).

## Basket verification (KAN-20)

[`backend/tests/test_compliance_verification.py`](../backend/tests/test_compliance_verification.py) verifies
whole baskets built from the fixtures:

| Basket | Verdict | Shows |
|---|---|---|
| Hidden allergen | `failed` | whey and casein caught through the ingredient list, coconut milk kept |
| Composite | `failed` | shellfish three levels deep and wheat inside soy sauce |
| Conflicting rule | `failed` | the strictest severity across members and the request is the one applied |
| Missing evidence | `escalated` | no list and an empty list are withheld, each with an escalation case |
| Corrupt evidence | `escalated` | an unreadable record and a cycle are withheld instead of crashing verification |
| Violation and uncertainty | `failed` | the uncertain item is still withheld, but no review is requested for a failed basket |

## Taste & preference memory (1.2.12, KAN-22)

A shopper's recurring preferences live on their household, at `/api/households/me/preferences`:

| Route | What it does |
|---|---|
| `GET` | Lists every stored preference and what it does (fields below) |
| `POST {kind, value}` | Remembers one. Saying the same thing again changes nothing |
| `PUT /{id} {kind, value}` | Changes it in place. A `learned` preference becomes the shopper's own (`source: user`) |
| `DELETE /{id}` | Forgets it. The row is deleted, not just unlinked |

`kind` is `dislike`, `like`, `brand` or `avoid_brand`. Values are trimmed, single-spaced and lower-cased,
and a blank value is 422. Saving the opposite of a stored preference (`like` vs `dislike`, `brand` vs
`avoid_brand`, same value), or changing one into a duplicate, is 409. The message asks the shopper to
change the existing preference instead. Changes return the household plus the described list.

| Field | Meaning |
|---|---|
| `effect` | `avoid` (dislike, avoid_brand) or `favour` (like, brand) |
| `status` | `applied`: a dislike leaves matching products out of new baskets and repairs, and a like or brand wins them close calls. `overridden`: every match breaks a mandatory restriction. `no_match`: nothing in the catalogue matches |
| `matches`, `match_count` | The products it applies to now (first five names) |
| `blocked` | For a like or brand: matching products a mandatory restriction rules out, with the restriction and whose it is (`Tree nuts (Jamie)`), or `Safety can't be confirmed` for an uncertain product |
| `hint` | Set when a dislike names an allergen or diet the household hasn't recorded (e.g. `peanuts`). A preference only matches product names, so the hint points to the household restrictions |
| `created_at`, `updated_at` | When it was saved and when it was last changed |

Dislikes match with the basket builder's own rule (`catalogue.disliked_by`: any word of the value against
the product's name, brand, category and tags), so `applied` shows exactly what will be left out. Likes
and brands must match every word.

**Later sessions.** A new request copies the saved preferences into its draft (`intake._apply_household`),
and confirming the request freezes them into the session's constraint set. A change or deletion
therefore applies from the next request on. A session that is already confirmed keeps what it applied,
as its record. Dislikes leave matching products out of the basket (unless the shopper pins one in an
edit) and out of nutrition repairs.

**Likes and preferred brands** (`NutritionComplianceAgent.favoured_products`) give matching products the
optimiser's existing `prefer` nudge: about 8% off their cost to the solver, the same nudge an edit uses
to keep current items. A liked product therefore wins a close call. It never breaks the budget or the
meal targets, and it is never bought just because it is liked. The item's reason ends with why
(`; you like firm tofu`), and the basket facts list it under `favoured_by_preferences` for the
explanation. On the default Balanced goal, likes do change baskets (tofu, tuna or spaghetti for Alex,
carrots for Riley). On Lowest cost and Best nutrition, with the current catalogue prices, the gap to the
cheapest or most nutritious option is wider than the nudge, so the basket stays the same.

**Mandatory restrictions first.** A preference never relaxes or replaces a restriction. Allergen and
diet screening runs on every candidate whatever the preferences say. Only products screened
`compliant` are nudged, so a liked product that breaks a restriction or can't be confirmed safe is
reported as blocked and never pulled in. A dislike beats a like, because disliked products are
removed before anything is nudged. A dislike that names an allergen stays a preference (with a hint)
and never becomes a restriction.

**Owner-only access and deletion.** Every route resolves the signed-in shopper's own household, and
no route takes a household id. Another shopper's preference id is 404, and dietitian and founder
accounts, which have no household, get 404 as well. Forgetting a preference deletes its row. Audit
records for preference changes name the kind and id only (`Forgot a dislike preference (#12)`), never
the value, so the preference log keeps no copy of a forgotten value. This follows the Stage 1
cross-tree constraint "Taste & Preference Memory implies Enhanced Data Protection". Records of
sessions that already applied a preference keep it: their confirmed constraint set, the intake audit
payload and the basket facts.

| Acceptance criterion | Tests |
|---|---|
| Store, show, change and delete | `test_a_preference_is_stored_and_shown_with_what_it_does`, `test_a_blank_preference_is_refused`, `test_a_preference_can_be_changed`, `test_changing_a_learned_preference_makes_it_the_shoppers_own`, `test_a_preference_cannot_duplicate_or_contradict_another`, `test_a_preference_can_be_forgotten`, `test_a_preference_of_an_unknown_kind_is_still_listed_and_can_be_forgotten`, plus the five `PreferencesPanel.test.tsx` cases |
| Applied in later sessions, mandatory restrictions first | `test_saved_preferences_apply_to_later_sessions`, `test_a_change_does_not_rewrite_a_session_already_confirmed`, `test_mandatory_restrictions_come_before_a_like`, `test_a_like_wins_a_close_call_in_later_baskets`, `test_a_like_never_pulls_in_an_unsafe_product`, `test_a_dislike_beats_a_like`, `test_a_like_does_not_override_the_shoppers_goal`, `test_a_dislike_never_stands_in_for_an_allergy` |
| Owner-only access and deletion | `test_preferences_need_sign_in`, `test_only_the_owner_can_see_change_or_forget_a_preference`, `test_staff_accounts_reach_no_ones_preferences`, `test_forgetting_a_preference_leaves_no_stored_copy` |
