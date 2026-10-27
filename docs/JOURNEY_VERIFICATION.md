# KAN-5 — Shopper journey verification (S05)

Release candidate on branch `Sanskar`, 27 October 2026. Owner: Sanskar. This is the evidence for
S05 in the delivery plan: an end-to-end run, the defects it found, and requirement traceability.

## 1. How the journey was run

| Run | How | LLM | Result |
|---|---|---|---|
| Manual | Every step of [DEMO_SCRIPT.md](DEMO_SCRIPT.md) driven through the API against a freshly seeded DB (`python -m app.seed --reset`) | Real model (`openai_compatible`, Groq `qwen/qwen3.8-27b`) | 3 defects found, all fixed (section 2) |
| Automated | `pytest tests/test_shopper_journey.py`: the same 14 steps as one test | Offline mock | Passes; runs in CI on every push |

Re-run the manual check after `python -m app.seed --reset`; the automated one with:

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
| 3 | 5 — item held for review | No item was held, so steps 5, 7 and 8 had nothing to show | A *"change one field"* correction of the budget to $110 meant the solver no longer chose the schnitzel | Demo script now says to correct the budget to $90; the 4-store seed keeps the schnitzel chosen for $90–$105 and 5–7 days |

Known issues from the 24 Oct audit fixed in the same pass (KAN-2/KAN-3 scope):

| Issue | Fix |
|---|---|
| An unrelated intake correction erased unanswered clarifying questions | `intake.correct` / `submit_form` keep open questions unless the new draft answers them |
| Non-protein nutrition targets were accepted but not enforced | `Requirements` enforces every catalogue nutrient (kcal, carbs, fat, fibre, veg serves). Intake maps common names ("fiber", "calories") and flags targets it can't check instead of silently ignoring them |

Regression tests: `test_journey_fixes.py`, `test_intake.py::test_unrelated_correction_keeps_unanswered_question`,
`test_basket_constraints.py::test_non_protein_nutrition_targets_are_enforced` and `::test_unsupported_nutrient_target_is_flagged_not_silently_kept`.
Each fails on the code before its fix.

Not fixed here (other owners): pantry/snack chat additions skip the final budget check (C04), old
dietary approvals are reused after an allergy's severity increases (R02/M04), and there is no account
registration (M02).

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

Every row is also covered end to end by `test_shopper_journey.py`.
