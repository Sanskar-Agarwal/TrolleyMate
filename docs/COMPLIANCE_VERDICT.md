# Compliance verdict contract (KAN-19 to KAN-24)

What the AI Nutrition & Compliance agent returns to the other agents, and how it was evaluated. Covers
requirements 1.2.10, 1.2.11 and 1.2.12, UC-06, UC-02 extension 4b (nutrition exceptions), and Stage 1
diagrams 7.4, 8.4 and 9.4.

Current contract checked against main `947a59c` on 29 October 2026. The KAN-23 evaluation
below retains its original 42-case run and `540bdc7` baseline; those are historical results,
not the current full-suite count.

| | |
|---|---|
| Schema | [`backend/app/services/compliance_verdict.py`](../backend/app/services/compliance_verdict.py) |
| Nutrition targets | [`backend/app/services/nutrition_targets.py`](../backend/app/services/nutrition_targets.py) |
| Preference rules | [`backend/app/services/preference_memory.py`](../backend/app/services/preference_memory.py) |
| Fixture catalogue | [`backend/tests/fixtures/compliance_cases.json`](../backend/tests/fixtures/compliance_cases.json) |
| Evaluation set (KAN-23) | [`backend/tests/agent_evaluation.py`](../backend/tests/agent_evaluation.py), with results in [`docs/evidence/agent-evaluation.md`](evidence/agent-evaluation.md) |
| Safety demo (KAN-24) | [`docs/SAFETY_DEMO.md`](SAFETY_DEMO.md), checked for every weekday by [`test_safety_demo.py`](../backend/tests/test_safety_demo.py) |
| Tests | [`test_compliance_contract.py`](../backend/tests/test_compliance_contract.py), [`test_compliance_verification.py`](../backend/tests/test_compliance_verification.py), [`test_nutrition_coverage.py`](../backend/tests/test_nutrition_coverage.py), [`test_preference_memory.py`](../backend/tests/test_preference_memory.py), [`test_agent_evaluation.py`](../backend/tests/test_agent_evaluation.py), [`PreferencesPanel.test.tsx`](../frontend/src/features/preferences/PreferencesPanel.test.tsx) |

## Verdicts

**Per product** — sequence 8.4, `classifyProduct()`; stored as `BasketItem.compliance`:

| Status | Meaning | Effect |
|---|---|---|
| `compliant` | No restriction conflict found, evidence complete | May enter the basket |
| `violation` | A known conflict with a mandatory restriction | Excluded |
| `uncertain` | Evidence missing, vague or untrustworthy, or a check that couldn't be completed | May be stored in a pending candidate as a withheld row; excluded from its usable total/nutrition and cannot be accepted (UC-06 ext 2a) |

These checks apply to the household/request restrictions being screened. With no restrictions,
`screen_product` returns `compliant` without checking ingredient completeness; this is not a
general certification of a product's safety or data quality.

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
  "schema_version": 3,
  "restrictions": [{"restriction": "tree_nuts", "severity": "severe", "label": "Tree nuts"}],
  "products": [{
    "product_id": 12, "product": "Basil Pesto 190g", "status": "violation", "confidence": 1.0,
    "findings": [{"kind": "contains", "restriction": "tree_nuts",
                  "ingredient": "basil pesto → pine nuts", "detail": "Contains pine nuts (tree_nuts)"}]
  }],
  "nutrition": { "...": "see below" }
}
```

- `findings[].kind` is one of `contains`, `ambiguous`, `may_contain`, `missing_data`, `data_error`,
  `check_failed`, `no_rule`, `human_review`. Schema version 3 (KAN-23) added `check_failed` and `no_rule`.
  Consumers show `detail` as text, so no consumer had to change.
  `data_error` marks evidence that can't be trusted (UC-06 failure scenario, 9.4 `dataSourceError`): an
  unreadable ingredient record or may-contain statement, or a composite that contains itself. The product
  is uncertain, so it is withheld and escalated; the readable rest of the record is still checked, so a
  known conflict still fails it.
- `contains` also covers a product whose label tags (`Product.tags`) name a restricted allergen when no ingredient record
  carries it (`The product is labelled shellfish, though no listed ingredient carries it`). A free-from
  claim (`gluten-free`, `dairy_free`) is never read as an allergen, and never clears one either.
- `ambiguous` is a vague label term the model judged `likely` (violation) or `possible` (uncertain). A
  `none` clears the term only at `COMPLIANCE_SAFETY_THRESHOLD` (default 0.95) or above. Below it, the term stays `ambiguous`
  and the product is uncertain.
- `check_failed` is a vague term the model couldn't judge, because the call failed, the reply was off the
  contract, or only the offline fallback answered and it found nothing. The fallback's rules can't vouch
  for a term the live model was needed for. 9.4 `dataSourceError` → Uncertain.
- `no_rule` is a restriction the knowledge base has no rule for (e.g. lupin), so no product can be
  confirmed free of it.
- May-contain statements are matched in label words: `Tree Nuts`, `peanut` and `dairy` count as
  `tree_nuts`, `peanuts` and `milk`.
- `ingredient` is the cascade path through composite ingredients.
- Deliberately configured offline mode uses the rule-based judge, including its limited known terms.
  A failed live call is different: its fallback `none` cannot clear the term. Provider setup failure
  enters `offline_unconfigured` and is disclosed by `/api/system/llm`; it is not a successful live check.
- A `violation` or `uncertain` product must carry at least one finding. Unknown keys are rejected,
  so a new piece of evidence has to be added to the schema first.

## Nutrition coverage (1.2.11)

Energy, protein, vegetables and staples are checked against targets already scaled to the
household size and meal schedule (`Requirements.from_constraints`). Default food quantities use
adult-equivalent portions, with breakfast and main quantities rounded independently. Explicit
per-person daily targets use full headcount. Withheld items don't count.

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
added after an edit, so basket reads (`basket_out`) report current nutrition too. The UI consumes
that current coverage and the server checks it again on acceptance.

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

The former animal-rennet expected failure is now a passing regression: `animal_rennet` is forbidden
for vegetarian and vegan rules, and the seed parmesan composite includes it. Dedicated tests cover
both diets and the seed cascade. The seed change applies to newly created demo data; startup does
not migrate an existing database's ingredient graph.

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
sessions that already applied a preference retain their confirmed instructions and basket facts.
Intake/routing prompts and raw replies are now omitted from oversight payloads; preference-keyed
payload data is redacted on write and read. Forgetting also scrubs those fields in the owner's legacy audit payloads. This does not erase confirmed shopping history.

| Acceptance criterion | Tests |
|---|---|
| Store, show, change and delete | `test_a_preference_is_stored_and_shown_with_what_it_does`, `test_a_blank_preference_is_refused`, `test_a_preference_can_be_changed`, `test_changing_a_learned_preference_makes_it_the_shoppers_own`, `test_a_preference_cannot_duplicate_or_contradict_another`, `test_a_preference_can_be_forgotten`, `test_a_preference_of_an_unknown_kind_is_still_listed_and_can_be_forgotten`, plus the five `PreferencesPanel.test.tsx` cases |
| Applied in later sessions, mandatory restrictions first | `test_saved_preferences_apply_to_later_sessions`, `test_a_change_does_not_rewrite_a_session_already_confirmed`, `test_mandatory_restrictions_come_before_a_like`, `test_a_like_wins_a_close_call_in_later_baskets`, `test_a_like_never_pulls_in_an_unsafe_product`, `test_a_dislike_beats_a_like`, `test_a_like_does_not_override_the_shoppers_goal`, `test_a_dislike_never_stands_in_for_an_allergy` |
| Owner-only access and deletion | `test_preferences_need_sign_in`, `test_only_the_owner_can_see_change_or_forget_a_preference`, `test_staff_accounts_reach_no_ones_preferences`, `test_forgetting_a_preference_leaves_no_stored_copy` |

## Changes by teammates in this area (since KAN-22)

Merged to main between KAN-22 and KAN-23 (`git log 031b7a6..540bdc7`). KAN-23 regression-tests each one.

| Change | What it does | Tests |
|---|---|---|
| FSANZ guidance retrieval for `assess_ingredient` (Sanskar, `f90dd12`) | [`services/allergen_guidance.py`](../backend/app/services/allergen_guidance.py) holds 21 short notes summarising FSANZ Standards 1.2.3 and 1.2.4. For each vague term the agent retrieves up to three notes that bear on the restriction (exact term first, then word overlap; generic words such as "emulsifier" don't match alone) and gives them to the model. Offline, the mock answers from a `likely` or `possible` note first. | `test_allergen_guidance.py`; evaluation T01–T03 |
| Learned dislikes (Sanskar, `ca4a8e8`) | `preference_memory.learn_from_declined_swap`: when the household has declined swaps to the same product twice, `substitution.reject` remembers it as a dislike with `source: learned`. It never overrides anything the shopper said, and it is listed and forgettable like any other preference. Since KAN-23 its audit line names the kind and id only (`Learned a dislike preference (#12)`). | `test_declining_the_same_swap_twice_is_learned_as_a_dislike`, `test_a_like_is_never_overridden_by_learning`; evaluation S13 |
| Repairs from the matching food group (Sanskar, `75dee5e`) | `nutrition_repairs` ranks protein foods first for a protein gap, vegetables for a vegetable gap, and grains for a staples gap, then gap closed, budget and cost. | `test_protein_gap_repairs_suggest_protein_foods_first`; evaluation T14 |
| Dietitian decisions reused only at the same or a stricter severity (Sanskar, `75dee5e`) | `_prior_decision` reuses a resolved case only if it was reviewed against every restriction that applies now, each at the same severity or stricter. A decision made before an allergy was added, or became more severe, is ignored and the product is screened again. | `test_dietitian_approval_is_not_reused_after_allergy_becomes_more_severe`, `test_stale_dietitian_approval_is_not_reused_after_new_allergy`; evaluation T12, T13 |

## Safety regression and capability evaluation (KAN-23)

A fixed evaluation set of 42 cases, [`backend/tests/agent_evaluation.py`](../backend/tests/agent_evaluation.py),
each run on a fresh database. The cases are grouped by the agent capability they exercise. An agent
perceives its environment, makes decisions using tools and takes actions (Lecture 2, *Components of an
Agent*; Tutorial 1, *AI Agent*). A judgement task is a bounded agent with explicit tools, and a high-impact
action gets approval and policy (Lecture 4 part 2, *Not every service should become an agent*):

| Capability | What is evaluated | Cases |
|---|---|---|
| Perception | Reading the household, the request and the product record: merging restrictions, hidden and composite ingredients, label wording, missing, corrupt or untagged data | 13 |
| Tool-based decisions | Decisions made with the agent's tools: the `assess_ingredient` model, the FSANZ notes it retrieves, earlier dietitian decisions, the priced catalogue | 14 |
| System actions | What happens to the basket: excluded, withheld, escalated, released only by a reviewer, re-checked when reused, audited | 15 |

Every case is tagged with its input: `normal`, `unsafe` (should be refused or flagged), `uncertain`
(evidence that can't be confirmed) or `failed_tool` (an outage, a malformed or off-contract reply, no
fallback). Every capability has each kind. Model replies and outages are scripted, so a run is
repeatable offline.

```bash
cd backend
pytest tests/test_agent_evaluation.py                                         # the regression gate (CI)
python -m tests.agent_evaluation --markdown ../docs/evidence/agent-evaluation.md   # record the results
```

**Observed results:** [`docs/evidence/agent-evaluation.md`](evidence/agent-evaluation.md) has every case,
with what was expected, what was observed, and the same set run on main (`540bdc7`) beside it.
The recorded KAN-23 branch run passed **42 of 42**; its historical main baseline `540bdc7` passed
**26 of 42**. The 16 baseline failures identify gaps fixed by that ticket. KAN-23 is now merged
into main; these numbers must not be read as a comparison with today's main.

### Integration follow-up — 29 October 2026

Two additional regressions in `test_agent_evaluation.py` cover increasing an unsafe pantry item
after a new allergy and increasing an already-withheld snack. The final extras set is screened
after all add/increase/decrease quantity changes, so a pin cannot reinsert either product as
compliant. The item is left out with an explanation. These tests are outside the fixed 42-case
evaluation and do not alter its historical counts.

Current intake also rejects unsupported restriction ids in extraction, corrections and structured
form patches. The animal-rennet fix above predates this integration. Historical limitations in
the generated evaluation report describe that report's original snapshot.

### Gaps found and fixed

| Gap on main | Cases | Fix |
|---|---|---|
| Brazil nuts, prawns, cream and barley had no allergen tags (seed catalogue expansion, KAN-16). Alex could add Brazil nuts despite Jamie's severe tree-nut allergy, Raw Prawns passed shellfish and vegetarian, and Pearl Barley passed coeliac | P12, S09 | Tags added in `seed/catalogue.json` (Chester's file), and `mixed nuts` retagged `tree_nuts` |
| A product labelled with an allergen whose ingredient record lacks the tag passed | P08 | The label is now evidence: `contains` "labelled ..., though no listed ingredient carries it" |
| May-contain in label words (`Tree Nuts`, `peanut`) wasn't matched | P07 | Label words map to tags (`dietary_rules.label_tag`) |
| A restriction with no rule (lupin) passed every product | P11 | `no_rule` → uncertain |
| A `none` the model was 60% sure of cleared the term | T05 | `none` clears only at the 0.95 threshold |
| A risk word off the contract (`High`, `LIKELY`) was read as `none` | T07 | `assess_ingredient.Output.risk` is `none \| possible \| likely` (case-insensitive), and an unreadable reply is `check_failed` |
| A malformed reply or an outage fell back to rules that cleared the term | T08, T09, S15 | A fallback `none` is `check_failed` → uncertain |
| With no fallback configured, an outage crashed verification | T10 | The failed check is `check_failed`: the item is withheld and escalated (9.4 `dataSourceError`) |
| An outage's fallback answer was cached for the life of the process | T11 | Fallback answers are kept for one request only |
| A chat edit carried pantry and snack extras into the rebuilt basket as `compliant` without re-screening them: a withheld item came back released, and peanut butter stayed after a new peanut allergy, so the basket could be accepted | S07, S08 | `basket_editing.edit` (Chester's file) screens carried-over extras again, leaves out any that no longer pass, and tells the shopper |
| Accepting a swap trusted the screening done when it was proposed | S10 | `substitution.accept` (Peter's file) re-checks the replacement through `NutritionComplianceAgent.recheck` |
| The learned-dislike audit line named the product | S13 | `substitution.reject` (Peter's file) names the kind and id only, as KAN-22 does |

### Uncertain items stay withheld pending authorised review

An uncertain item is withheld, left out of the total and nutrition, and escalated to the dietitian (S02,
T10). While it is withheld the basket can't be accepted or meal-planned (S03). No shopper can start or
decide its review (S04); a `passed` decision from an authorised dietitian or founder releases it (S05).
Rebuilding the basket keeps it withheld under the same case (S06). A chat edit (S07) or an earlier
swap (S10) can't bring it back as safe,
and an outage can't clear it (S15). `test_agent_evaluation.py` names these cases, so one can't drop out
of the set unnoticed.

### Limitations

Recorded with the results in the evidence file. The ones that matter most:

- **Offline knowledge.** In offline mode the rule-based judge clears any vague term it has no rule or
  note for (`none` at 0.97, T04). A live model can assess additional terms, but its confidence is not
  a guarantee of correctness.
- **Unknown restrictions** make every product uncertain (P11). That's safe, but it floods the review
  queue. Current intake rejects unsupported ids in extraction, corrections and form patches;
  legacy or externally supplied data can still reach this screening safeguard.
- **Re-verifying a built basket** (`POST /baskets/{id}/verify`, API only) fails it and blocks
  acceptance (S14). It still leaves the unsafe product in the total and labels the basket `verified`.
- **Safety lock scope.** UC-06's failure scenario locks the whole basket. The code withholds only the
  affected product, while acceptance and meal-plan gates block a basket containing withheld items.
  This difference from the design remains an explicit prototype limitation.
- **Reused human decisions.** Reuse checks product id, household id, restriction severity coverage and a fingerprint of
  the reviewed product/ingredient evidence. Changed evidence invalidates approval reuse. Legacy
  cases without a fingerprint must be re-verified; an active review must restart if its evidence changes.
- **Prompt injection.** Label text reaches the model verbatim. The output contract, the 0.95 threshold
  and the FSANZ notes limit what a confident wrong answer can do. They don't remove the risk.
- **Evaluation model coverage.** This 42-case safety evaluation uses scripted model replies and
  outages. The separate [28 October UAT](UAT_2026-10-28.md) records live intake/routing and a shopper
  journey; it is not a live-model run of this safety evaluation or a Campus Qwen evaluation.

| Acceptance criterion | Evidence |
|---|---|
| Run a fixed evaluation set covering perception, tool-based decisions and system actions, including unsafe/uncertain inputs and failed tools | `test_agent_evaluation.py`: the set's make-up is pinned (42 cases, every capability × input kind), and every case runs in CI |
| Record observed results and limitations | [`docs/evidence/agent-evaluation.md`](evidence/agent-evaluation.md): expected, observed and the main baseline per case, plus limitations |
| Uncertain items stay withheld pending authorised review | S02–S07, S10, S15 and T10, listed in `WITHHELD_UNTIL_REVIEW` |

## Safety demo and refusals that say why (KAN-24)

[`SAFETY_DEMO.md`](SAFETY_DEMO.md) is a three-minute segment for the week 13 demo. It shows hidden allergens
refused and an uncertain item left unresolved, not presented as safe. Specials are priced by weekday, so
[`test_safety_demo.py`](../backend/tests/test_safety_demo.py) runs the segment once for every weekday.

**A refused chat request names what was found.** When a chat edit asks for a product the household can't have,
`basket_editing.compliant_match` (Chester's file) now considers only the best-matching products, and refuses
with `Finding.refusal()`:
*Honey Muesli Bars 6pk isn't safe for your household: contains whey powder (lactose); contains almonds (tree nuts).*
An uncertain product reads *... can't be confirmed safe for your household yet: ...*. Before this, the request
fell through to a weaker match, so *"add honey muesli bars"* added Honey 500g and *"add sugar free mints"* added
Free Range Eggs. The unsafe product was never added, but the shopper wasn't told it had been refused.

### Acceptance audit — 30 October 2026

Out-of-range model confidence (including 85 rather than 0.85) is rejected as an incomplete
check instead of clamped to a confident answer. The T06 evaluation scenario now expects
`uncertain` with a `check_failed` finding. The historical evaluation report retains the
original run; current suite results are recorded in [the new UAT report](UAT_2026-10-30.md).
Additional tests cover changed product data before and during human review, all supported
custom nutrition minimums, and private intake/routing audit payloads.
