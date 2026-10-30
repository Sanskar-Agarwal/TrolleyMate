# KAN-5 — Shopper journey verification, 27 October 2026 (S05)

Release candidate on branch `Sanskar`, 27 October 2026. Owner: Sanskar. This is the evidence for
S05 in the delivery plan: an end-to-end run, the defects it found, and requirement traceability.

Sections 1–5 preserve the **27 October record**; their results are not a fresh run of current
main. The numbered demo steps refer to the historical [demo script](DEMO_SCRIPT.md).
For the latest verified version, use [README verification](../README.md#verification); for
current presentation guidance, use the [seven-minute release checklist](RELEASE_CHECKLIST.md).
Section 6 records the status update after the 29 October integration.

## 1. How the journey was run

| Run | How | LLM | Result |
|---|---|---|---|
| Manual | Every step of [DEMO_SCRIPT.md](DEMO_SCRIPT.md) driven through the API against a freshly seeded DB (`python -m app.seed --reset`) | Real model (`openai_compatible`, Groq `qwen/qwen3.8-27b`) | 3 defects found, all fixed (section 2) |
| Automated | `pytest tests/test_shopper_journey.py`: the same 14 steps as one test | Offline mock | Passed in this run; CI runs on pull requests and pushes to `main` |

Use a disposable database for a manual rerun; do not reset a shared database. Run the automated check with:

```bash
cd backend && .venv/bin/python -m pytest tests/test_shopper_journey.py
```

**Real-LLM note:** on Groq's free tier the burst of `assess_ingredient` calls during the first basket
build hit the output-tokens-per-minute limit (HTTP 429). The app fell back to the offline mock for
those calls as designed, and the badge turned amber. For the live demo, use a key with a higher limit
or the Campus Qwen proxy, or say the app is in fallback mode.

## 2. Defects found and fixed

| # | Demo step | What broke | Cause | Fix |
|---|---|---|---|---|
| 1 | 9 — *"Replace the lentils with chicken"* | Refused as a conflict with $31 of budget left, plus a confusing "maximum limit is 24 meals" message | The optimiser caps any one food group at 40% of protein servings. The edit pinned 3 packs of chicken (12 servings vs a cap of 11.2), so no basket was feasible | An explicit shopper pin may now exceed the soft variety cap (`basket_optimiser.py`) |
| 2 | 7–8 — dietitian release | The basket kept saying *"… is held until a dietitian confirms"* after release; the explanation still listed it as withheld, with the old total | The review decision changed the item but not the basket's recorded notices and facts | `escalation._apply` clears the held notice and the `withheld` fact, adds a released/removed notice, and refreshes the total |
| 3 | 5 — item held for review | No item was held, so steps 5, 7 and 8 had nothing to show | A *"change one field"* correction of the budget to $110 meant the solver no longer chose the schnitzel | The demo request was changed to $90 for this run. Current presenters must prepare a labelled review case; product selection is not guaranteed. |

Known issues from the 24 Oct audit fixed in the same pass (KAN-2/KAN-3 scope):

| Issue | Fix |
|---|---|
| An unrelated intake correction erased unanswered clarifying questions | `intake.correct` / `submit_form` keep open questions unless the new draft answers them |
| Non-protein nutrition targets were accepted but not enforced | `Requirements` enforces every catalogue nutrient (kcal, carbs, fat, fibre, veg serves). Intake maps common names ("fiber", "calories") and flags targets it can't check instead of silently ignoring them |

Regression tests: `test_journey_fixes.py`, `test_intake.py::test_unrelated_correction_keeps_unanswered_question`,
`test_basket_constraints.py::test_non_protein_nutrition_targets_are_enforced` and `::test_unsupported_nutrient_target_is_flagged_not_silently_kept`.
Each fails on the code before its fix.

A browser walkthrough of the same script (27 Oct, real LLM) found one more:

| # | Demo step | What broke | Fix |
|---|---|---|---|
| 4 | 8, 10 | The summary paragraph at the top of the basket kept the build-time total and items after a dietitian release or an accepted swap | `basket_builder.refresh_explanation` re-syncs the recorded facts and regenerates the summary; called after every review decision and accepted swap |

## 3. Seed data: four competing retailers

The catalogue (schema 1.1.0) now prices every product at four stores. They differ by category
multipliers, their own specials and stock exclusions, so each store wins some items:

| Retailer | Feed | Profile |
|---|---|---|
| GreenGrocer Express | daily catalogue | premium; cheaper fruit and veg |
| ValueMart | daily catalogue | budget; cheaper pantry and carbs |
| FreshCo | partner API (simulated live) | seeded 30 h stale to show the refresh |
| Harvest Market | daily catalogue | discount; cheaper protein and dairy, dearer fruit and snacks |

The **Compare stores** tab now shows **Cheapest from each store**: the split basket grouped by the
store each item is cheapest at, with a subtotal per store and the saving against the next-cheapest
store (`split_plan` in `MarketAnalystAgent.compare`).

## 4. Requirement traceability

| Req | Feature | Code | Tests | Demo step |
|---|---|---|---|---|
| 1.2.1 | NL intake & confirmation | `workflows/intake.py`, `llm/tasks/extract_constraints.py` | `test_intake.py` | 2–3 |
| 1.2.2 | Constrained baskets, 5 goals | `workflows/basket_builder.py`, `optimisation/*` | `test_basket_flow.py`, `test_basket_constraints.py` | 4 |
| 1.2.3 | Meal plans from accepted baskets | `workflows/meal_planning.py`, `services/meal_planner.py` | `test_meal_planning.py` | 12 |
| 1.2.4 | Infeasibility negotiation | `workflows/negotiation.py` | `test_basket_flow.py`, `test_review_fixes.py` | 13 |
| 1.2.5 | Substitution with trade-off | `workflows/substitution.py` | `test_basket_flow.py` | 10 |
| 1.2.6 | Buy-timing advice | `services/buy_timing.py` | `test_basket_flow.py` | 11 |
| 1.2.7 | Multi-retailer ingestion & units | `services/pricing/*`, `seed/catalogue.json` | `test_pricing.py`, `test_units.py`, `test_catalogue.py` | 4, 11 |
| 1.2.8 | Savings vs named baseline | `agents/market_analyst.py` | `test_savings_comparison.py` | 11 |
| 1.2.9 | Conversational basket editing | `workflows/basket_editing.py` | `test_journey_fixes.py`, `test_basket_flow.py` | 9 |
| 1.2.10 | Cascading allergen checks | `agents/nutrition_compliance.py`, `services/dietary_rules.py` | `test_compliance_contract.py`, `test_compliance_verification.py` | 4–5 |
| 1.2.11 | Nutrition coverage | `agents/nutrition_compliance.py`, `services/nutrition_targets.py` | `test_nutrition_coverage.py` | 4 |
| 1.2.12 | Preference memory | `services/preference_memory.py`, `api/preferences.py` | `test_preference_memory.py` | 1 |
| 1.2.13 | Accounts & household profiles | `api/households.py`, `domain/*` | `test_preference_memory.py`, `test_shopper_journey.py` | 1 |
| 1.2.14 | Explanations & audit | `agents/technical_manager.py`, `api/audit.py` | `test_basket_flow.py::test_explanations_and_audit` | 6, 14 |
| 1.2.15 | Dietitian review queue | `workflows/escalation.py`, `api/escalations.py` | `test_basket_flow.py`, `test_journey_fixes.py` | 5, 7–8 |

`test_shopper_journey.py` samples this full journey. It does not exercise every acceptance
criterion or failure branch; use the focused tests and the release acceptance matrix as well.

## 5. Audit of every ticket marked Done (27 Oct)

Each Done ticket was checked against its acceptance criteria in the 12 Oct delivery plan: by the
test suite, by targeted API probes against a fresh mock-mode database, in the browser, and with
`scripts/verify_clean.py` plus a Docker build and run.

**Integration gap found:** Maaz's KAN-25 to KAN-29 work (15 commits on `Maaz`) had never been merged,
so the release was missing it. It's now merged into `Sanskar`, conflict-free, and every test passes.

| Ticket | Result | Notes |
|---|---|---|
| KAN-1 S01 contracts & baseline | Pass | `docs/API_CONTRACTS.md`, `docs/DECISIONS.md` (now merged) |
| KAN-2 S02 intake | Fixed | Unrelated corrections dropped open questions (fixed); cancel keeps the last confirmed set |
| KAN-3 S03 baskets & goals | Fixed | All 5 goals in budget and safe; non-protein targets now enforced; shopper pins may exceed the variety cap |
| KAN-4 S04 meal plans | Pass | Uses only bought items and reports gaps |
| KAN-7 P01 solver contract | Pass | Fixture tests |
| KAN-8 P02 substitutions | Fixed | Rejected swaps aren't re-offered and unsafe ones are never offered; the summary and explanation now follow an accepted swap |
| KAN-9 P03 negotiation | Pass | The minimum extra budget really is the minimum ($0.50 less is infeasible) |
| KAN-10 P04 buy timing | Pass recorded | The original audit reported no "wait" advice for perishables. Current code skips daily staples and prevents waiting beyond shelf life; this row does not prove that every perishable is excluded. Advice does not change the basket. |
| KAN-13 C01 data contract | Pass | Provenance updated for 4 retailers (schema 1.1.0) |
| KAN-14 C02 ingestion & units | Pass | Invalid sizes and units aren't normalised |
| KAN-15 C03 savings | Pass | Every baseline works; incomplete options never claim savings |
| KAN-16 C04 chat editing | Fixed | Pantry/snack additions could exceed the budget ($8.80 on $7) and were dropped by the next edit; now reserved from the budget and kept |
| KAN-17 C05 price verification | Pass | Its fix is already in `main` |
| KAN-19 R01 verdict contract | Pass | Contract tests |
| KAN-20 R02 allergen cascade | Fixed | A dietitian "safe" decision was reused after an allergy became more severe; now only reused at the same severity or stricter |
| KAN-21 R03 nutrition coverage | Fixed | Repairs for a protein gap suggested 2 kg of rice first; matching food groups now come first |
| KAN-22 R04 preferences | Pass | Owner-only; can be deleted |
| KAN-25 M01 interfaces & CI | Pass after merge | CI runs on PRs and on `main` |
| KAN-26 M02 profiles | Pass after merge | Another shopper can't edit; a failed save keeps the profile (UI and API) |
| KAN-27 M03 explanations & audit | Fixed after merge | The drawer shows its source records; the summary, totals and nutrition now refresh after changes |
| KAN-28 M04 review queue | Fixed after merge | Expired reviews are requeued to another reviewer; held notices are cleared on decision |
| KAN-29 M05 clean deployment | Pass after merge | `verify_clean.py` PASSED on the merged commit (pinned install, tests, build, offline and fallback startup) |
| KAN-31 Docker & CI/CD | Pass | Image builds; container serves the UI and API from a clean start |

## 6. Status update — 29 October 2026

This update supersedes the earlier gap list. Main `947a59c` includes the acceptance fixes from
PR #13 and the safety evaluation/integration fixes from PR #14. The latest local results were
416 backend tests and 57 frontend tests; [main CI run 40806441408](https://github.com/rkn321/ELEC5620-Group5-TrolleyMate/actions/runs/40806441408)
passed and published the Docker image. See [README verification](../README.md#verification)
for the versioned evidence. These results do not complete human release approval.

### Previously listed gaps now implemented

| Area | Current evidence |
|---|---|
| Shopper registration | `api/auth.py` registration route and `test_registration.py` |
| Age-based portions, quantity-safe meals and cancellation | `OPTIMISATION_AND_MEALS.md`, `test_meal_planning.py`, `test_build_cancellation.py` |
| CSV/JSON import and configurable partner HTTP feed | `services/pricing/importer.py`, `price_sources.py`, `test_price_feeds.py`; default prices remain illustrative |
| Missing unit-price labels and basket-edit change summaries | `PriceComparison.tsx`, `test_chat_features.py` |
| Price questions and household changes through chat | `PersonalShopperAgent`, `test_chat_features.py` |
| Learned preferences and retrieved allergen guidance | `test_preference_memory.py`, `test_allergen_guidance.py` |
| Unsafe extras and substitution acceptance | Fixed 42-case [safety evaluation](evidence/agent-evaluation.md), plus two separate quantity-increase integration regressions |
| Reviewer reassignment and local startup portability | `ReviewQueuePage.tsx`, `test_review_queue.py`, `scripts/run-backend.mjs` |

### Current limits and remaining evidence

- The seeded four-retailer catalogue/history is demonstration data. The importer and optional
  HTTP adapter do not establish a live commercial retailer integration or actual stock availability.
- Basket objectives use product-level estimates; the recipe planner uses quantities, durations
  and shelf life but can still report unfilled meals. It does not generate full cooking instructions.
- Substitution presents one candidate at a time. Negotiation offers budget increases or fewer
  days. Top-three alternatives, proactive stock alerts and additional trade-off types remain
  backlog ideas, not claims of delivered functionality.
- Buy timing uses recurring weekday discounts, with no price-history chart. The service skips
  daily staples and prevents deferral beyond a product's shelf life. Explicit insufficient-history
  and out-of-stock substitution failure evidence remains part of KAN-11's review work.
- No dedicated audit charts or automatic shopper toast for a dietitian decision is provided.
  Live model availability must be checked for the chosen demo; the 27 October rate-limit result
  is historical, and later live checks are recorded in [the 28 October UAT](UAT_2026-10-28.md).
- CODEOWNERS now names the four configured owners; Peter's area still falls back to the default
  owner. Branch protection, Jira integration, sprint reviews and tags require their own records.
- GHCR publication supplies a runnable image. Hosted operation is separate; the checked demo
  uses SQLite and one API process. See [deployment guidance](DEPLOYMENT.md) for setup and recovery.
- KAN-12/18/30 still require retrospective/process evidence and the final contribution/submission
  artifacts. A clean-build script is available; the final archive, checksum and extract/run result
  must identify the actual selected release. The [release checklist](RELEASE_CHECKLIST.md) keeps
  rehearsal, feedback, agreed contributions and sign-off unverified until supporting records exist.
