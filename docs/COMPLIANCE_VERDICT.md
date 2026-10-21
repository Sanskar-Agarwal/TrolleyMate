# Compliance verdict contract (KAN-19)

What the AI Nutrition & Compliance agent returns to the other agents. Covers requirements
1.2.10 and 1.2.11 (interfaces only), UC-06, and Stage 1 diagrams 7.4, 8.4 and 9.4.

| | |
|---|---|
| Schema | [`backend/app/services/compliance_verdict.py`](../backend/app/services/compliance_verdict.py) |
| Nutrition targets | [`backend/app/services/nutrition_targets.py`](../backend/app/services/nutrition_targets.py) |
| Fixture catalogue | [`backend/tests/fixtures/compliance_cases.json`](../backend/tests/fixtures/compliance_cases.json) |
| Tests | [`backend/tests/test_compliance_contract.py`](../backend/tests/test_compliance_contract.py) |

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
  "schema_version": 1,
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

`adequate`, `provided`, `required`, `gaps` and `suggestions` are unchanged. New fields:

- `coverage`: one entry per target, `{nutrient, required, provided, coverage_pct, met}`
- `targets`: the target version the requirements were built from (`prototype-2026-10`)

`gaps` lists exactly the unmet targets, and `adequate` is true only when every target is met.

## Prototype nutrition targets

Prototype values for the demo, not dietary advice. They match the constants the optimiser already
uses in `Requirements`, and a test keeps the two in step.

| Target | Per | Reference | Source | Demo assumption |
|---|---|---|---|---|
| 550 kcal | person-meal | 8,700 kJ/day average adult intake (%DI) | FSANZ Food Standards Code, Std 1.2.8 | About a quarter of the day per meal; snacks bought elsewhere |
| 22 g protein | main meal | RDI 64 g/day men, 46 g/day women (19–70) | NHMRC Nutrient Reference Values (2006) | 64 g over three meals, rounded up |
| 2 serves veg | main meal | 5–6 serves/day, adults 19–50 (serve = 75 g) | NHMRC Australian Dietary Guidelines (2013) | The basket covers the planned main meals only |

Carbohydrates/staples have no separate gram target: energy stands in for them, and the optimiser
requires one carbohydrate serving per main meal.

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
