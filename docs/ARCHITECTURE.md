# Architecture — from the Stage 1 design to the code

Trolley Mate implements the **Supervisor–Worker with deterministic services and a human
approval gate** architecture from Stage 1 §4.2. This page maps every Stage 1 model to the code
that realises it, so a reviewer can check completeness.

```
 Shopper ─▶ React UI ─▶ FastAPI /api ─▶ AgentContext (one per request)
                                          ├─ PersonalShopperAgent  «supervisor»
                                          │    workflows/intake, basket_builder, negotiation,
                                          │    substitution, meal_planning, basket_editing
                                          ├─ MarketAnalystAgent    «worker»   ─▶ services/pricing, buy_timing
                                          ├─ NutritionComplianceAgent «worker» ─▶ dietary_rules ─▶ escalation ─▶ Dietitian
                                          └─ TechnicalManagerAgent «governance» ─▶ AuditRecord (every decision)
                                        BasketOptimiser (SciPy MILP) — deterministic, no LLM
                                        LLMService ─▶ mock | OpenAI-compatible (Campus Qwen, Ollama, OpenAI) | Anthropic
```

## Primary workflow (Figure 4.2, steps 1–5)

`backend/app/workflows/basket_builder.py::build`

| Step | Stage 1 | Code |
|---|---|---|
| 1 | Supervisor requests pricing | `ctx.analyst.offers(...)` — cheapest fresh quote per product; stale quotes refreshed through `PriceSource` |
| 2 | Catalogue / price data | `services/pricing/price_sources.py` (`CatalogueFeedAdapter`, `PartnerApiAdapter`) |
| 3 | Optimise under constraints | `optimisation/basket_optimiser.py` — integer program, objective from an `OptimisationStrategy` |
| 4 | Validate dietary compliance | `ctx.compliance.verify(...)` — cascading ingredient walk; uncertain items withheld + escalated |
| 5 | Present with explanation | `ctx.manager.explain_for(...)` — LLM text generated **only** from recorded facts |

Screening runs before pricing in code (so we never price products that can't be bought); the
order of judgements is otherwise exactly Figure 4.2. Infeasibility (extension 3a) hands off to
`workflows/negotiation.py`.

## Class diagram (Figure 5) → code

| Package | Class | File |
|---|---|---|
| AgentRoles | `Agent {abstract}` — `perceive`, `log` (+ `think`) | `agents/base.py` |
| | `PersonalShopperAgent «supervisor»` — `orchestrate`, `extractConstraints` | `agents/personal_shopper.py` |
| | `MarketAnalystAgent «worker»` — `compare`, `explainDifference` | `agents/market_analyst.py` |
| | `NutritionComplianceAgent «worker»` — `verify`, `raise`, `safetyThreshold` | `agents/nutrition_compliance.py` |
| | `TechnicalManagerAgent «governance»` — `record`, `explainFor` | `agents/technical_manager.py` |
| Optimisation | `BasketOptimiser` — `solve`, `isFeasible`, `solverTimeoutMs` | `optimisation/basket_optimiser.py` |
| | `OptimisationStrategy «interface»`, `LowestCost`, `BestNutrition`, `Balanced` (+ `LeastWaste`, `FastestToCook`) | `optimisation/strategies.py` |
| HouseholdProfiles | `Shopper` (as `User`, role = shopper), `Household`, `HouseholdMember`, `DietaryProfile` | `domain/household_profiles.py` |
| RequestsConstraints | `ShoppingSession`, `ShoppingRequest`, `ConstraintSet`, `Constraint {abstract}`, `BudgetConstraint`, `DietaryConstraint {relaxable=false}`, `MealCountConstraint`, `NutritionalConstraint` | `domain/requests_constraints.py` |
| BasketProducts | `Basket`, `BasketItem`, `Product`, `Ingredient` (composite), `Substitution`, `MealPlan` | `domain/basket_products.py` |
| Pricing | `Retailer`, `PriceQuote` (`isStale`, `supersede`, `markUnavailable`), `PriceSource «interface»`, `CatalogueFeedAdapter`, `PartnerApiAdapter` | `domain/pricing.py`, `services/pricing/price_sources.py` |
| | `SavingsReport` | computed dict from `MarketAnalystAgent.compare` |
| SafetyAudit | `ComplianceVerdict`, `EscalationCase` (`assignTo`, `beginReview`, `requestInformation`, `supplyInformation`, `resolve`), `CaseStatus`, `Dietitian` (as `User`, role = dietitian), `AuditRecord` | `domain/safety_audit.py`, `workflows/escalation.py` |

## Use cases → workflow, API, UI

| Use case | Workflow | API | UI |
|---|---|---|---|
| UC-01 Extract constraints | `workflows/intake.py` | `POST /sessions/{id}/requests`, `/requests/{id}/clarify·correct·form·confirm·cancel`, `POST /sessions/{id}/chat` | `features/intake/` |
| UC-02 Optimise basket | `workflows/basket_builder.py` | `POST /sessions/{id}/basket` | `features/basket/` |
| UC-03 Infeasibility negotiation | `workflows/negotiation.py` | `POST /sessions/{id}/negotiate` | `features/negotiation/` |
| UC-04 Smart substitution | `workflows/substitution.py` | `POST /baskets/{id}/items/{item}/substitute`, `/substitutions/{id}/accept·reject` | `features/substitution/` |
| UC-05 Price comparison | `MarketAnalystAgent.compare` | `GET /baskets/{id}/comparison?baseline_id=` | `features/pricing/` |
| UC-06 Allergen compliance | `NutritionComplianceAgent.screen/verify` | `POST /baskets/{id}/verify`, `GET /products/{id}/compliance` | `features/compliance/` |
| UC-06 ext Human review | `workflows/escalation.py` | `/escalations`, `/escalations/{id}/begin·request-info·resolve·assign` | `features/review/` |
| UC-07 Transparency & audit | `TechnicalManagerAgent` | `GET /baskets/{id}/explain`, `/items/{item}/explain`, `/audit`, `/audit/stats` | `features/explain/`, `features/admin/` |
| UC-08 Meal plan | `workflows/meal_planning.py`, `services/meal_planner.py` | `POST /baskets/{id}/meal-plan` | `features/mealplan/` |
| UC-09 Conversational editing | `workflows/basket_editing.py` | `POST /baskets/{id}/edit` (or chat) | chat panel |
| UC-10 Household profiles | `api/households.py`, `api/preferences.py` | `/households/me…` | `features/profile/`, `features/preferences/` |
| 1.2.6 Buy-timing | `services/buy_timing.py` | `GET /baskets/{id}/buy-timing` | `features/buytiming/` |

## State machines (Section 9) → code

| Diagram | Where |
|---|---|
| 9.1 ShoppingRequest | `RequestStatus` + `IntakeStage` (draft substates) in `domain/enums.py`; transitions in `workflows/intake.py`. Third correction → form mode; cancel before commit preserves the previous set; confirm is one transaction. |
| 9.2 Substitution | `SubStatus` pending → accepted / rejected / discarded in `workflows/substitution.py`; rejected swaps stored on the session and never re-offered. |
| 9.3 PriceQuote | `QuoteStatus` fresh / stale / unavailable / superseded; `MarketAnalystAgent.current_quote` refreshes stale quotes, superseding (never overwriting) them. |
| 9.4 ComplianceVerdict | `VerdictStatus` passed / failed / escalated in `NutritionComplianceAgent.verify`. |
| 9.5 EscalationCase | `CaseStatus` open → assigned → under_review ⇄ awaiting_information → resolved, plus the `after(review SLA)` release in `workflows/escalation.py`. |

## Where the LLM sits (criterion 2: perceive, decide, interact)

| Capability | Agent | LLM task | What it does |
|---|---|---|---|
| Perceive | Personal Shopper | `extract_constraints` | Free text → structured constraints; asks instead of assuming |
| Perceive | Nutrition & Compliance | `assess_ingredient` | Judges vague label terms ("natural flavours") against each allergy |
| Decide | Personal Shopper (supervisor) | `classify_intent` | Routes each chat message to the right workflow / worker |
| Decide | Personal Shopper | `parse_edit` | "Replace the beef with chicken and make it $10 cheaper" → solver pins |
| Interact | Personal Shopper | `tradeoff`, `negotiation_message`, `meal_plan_notes` | States trade-offs and options in plain language |
| Interact | Market Analyst | `market_insight` | Explains why one store is cheaper |
| Interact | Technical Manager | `explain` | Grounded "why this?" explanations from audit facts |
| Interact | Nutrition & Compliance | `supply_information` | Answers a dietitian's question from the product record |

The LLM never computes prices, solves the basket, or declares an item safe — those are
deterministic, which is what keeps every recommendation attributable (Stage 1 §4.1).

## Resilience

- `LLM_FALLBACK_TO_MOCK=true`: any provider error or invalid JSON falls back to the task's
  offline mock; the result is flagged `fell_back` in the UI badge, the activity feed and the audit log.
- Structured outputs are validated with Pydantic before use.
- Anthropic: structured outputs + server-side refusal fallback; on a 400 it retries with
  prompt-only JSON. OpenAI-compatible: JSON mode, retried without it if the server rejects it;
  `<think>` blocks (Qwen3) are stripped.
