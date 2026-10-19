# Optimiser interface contract (P01, Stage 1 1.2.2 / 1.2.4)

The interface between the basket workflows (UC-02 build, UC-03 negotiation, UC-04 substitution, UC-09
editing) and `BasketOptimiser`. Implementation is owned by Intake & Optimisation (S03); this page and
the fixtures below are the regression contract that both sides test against.

- Code: `backend/app/optimisation/` (`types.py`, `strategies.py`, `basket_optimiser.py`)
- Fixtures: `backend/tests/fixtures/optimiser_cases.json`
- Runnable spike: `cd backend && python -m tests.optimiser_spike`
- Tests: `backend/tests/test_optimiser_contract.py`

> Agreed: Yat Man Peter Ho (Negotiation & Substitution) / Sanskar (Intake & Optimisation) — date: ____

## 1. Inputs

`BasketOptimiser(solver_timeout_ms=SOLVER_TIMEOUT_MS).solve(req, strategy, candidates, *, min_qty, max_qty, prefer, enforce_budget=True)`

### `Requirements` — what the basket must cover

Derived from a confirmed `ConstraintSet` by `Requirements.from_constraints(cs, days=?, budget=?)`.

| Field | Meaning | Derivation |
|---|---|---|
| `household_size` | people | `household_size`, default 1 |
| `days`, `meals_per_day` | horizon | `days` (default 7), `meals_per_day` (default 2) |
| `budget` | dollars, or `None` = uncapped | `budget` |
| `portions` | adult-equivalent eaters (a child ≈ 0.6) | `portions`, default `household_size` |
| `person_meals`, `main_meals`, `breakfast_meals` | meal counts | ⌈`meal_schedule(days, meals_per_day)` × portions⌉ |
| `kcal` | minimum energy | 550 × person-meals |
| `protein_g` | minimum protein | max(22 g × main meals, any `nutritional_targets` protein minimum × portions × days) |
| `veg_serves` | minimum veg | 2 × main meals |
| `protein_servings`, `carb_servings` | role servings | 1 per main meal each |
| `breakfast_servings` | breakfast-tagged servings | ⌈1.6 × breakfasts⌉ |
| `extra_minimums` | other nutrient targets (e.g. `fibre_g`) as basket totals | `nutritional_targets` × portions × days; kcal/veg targets raise the defaults instead |

### `Candidate` — one purchasable product

`product`, `retailer`, `price` (pack price at the cheapest fresh quote), `quote_id`, `unit_price`,
`unit_basis`, `compliance` (`compliant` | `uncertain`), `on_special`. The role is the product category
when it is `protein`, `carb` or `veg` **and** the category or a tag is an ingredient of some main recipe
(`seed/recipes.json`), so breakfast oats never count as dinner carbs; `role_units` is servings (veg: `veg_serves`).

Candidates are **already screened**: products with a dietary/allergen violation never reach the solver,
and any candidate marked `violation`, unpriced or priced ≤ 0 is dropped. Dietary rules are therefore not
solver constraints and no goal weight can trade them away.

### Keyword arguments

| Argument | Used by | Meaning |
|---|---|---|
| `min_qty` / `max_qty` `{product_id: packs}` | UC-09 editing | Hard pins; non-negative whole numbers, min ≤ max, a required product must be in the pool |
| `prefer` `{product_id}` | editing, preferences | Small objective discount so an edit doesn't reshuffle the basket |
| `enforce_budget=False` | UC-03 | Drops the budget row to price the cheapest way to meet everything else |

## 2. Goal weights (`OptimisationStrategy`)

The solver minimises Σ coefficient × packs. `adjust(req)` may only **raise** requirements.

| Goal | `coefficient(c)` | `adjust(req)` |
|---|---|---|
| Lowest cost | price | — |
| Best nutrition | price × (1 − 0.6 × density / max density), density = (0.04·protein + 0.08·fibre + 0.5·veg serves) / price | veg × 1.6, protein × 1.1 |
| Least waste | role units × (1.6 if perishable else 1) + 0.05 × price | — |
| Fastest to cook | prep minutes per serving × servings + 0.05 × price | — |
| Balanced | 0.55·price + 0.2·waste + 0.15·prep + 0.1·(1 − nutrition), each normalised to the candidate set's maximum | — |

Modifiers on every goal: a `prefer`red product gets −(8 % × |k| + 0.01); an `uncertain` product gets
+(10 % × |k| + 0.01), so certain items win ties.

## 3. Constraint checks

| Check | Row |
|---|---|
| Budget | Σ price × packs ≤ budget (skipped when `budget is None` or `enforce_budget=False`) |
| Energy / protein / veg | Σ kcal ≥ `kcal`; Σ protein_g ≥ `protein_g`; Σ veg_serves ≥ `veg_serves` |
| Extra nutrients | Σ nutrient ≥ each `extra_minimums` value |
| Role servings | protein servings ≥ `protein_servings`; carb ≥ `carb_servings`; breakfast-tagged non-role items ≥ `breakfast_servings` |
| Breakfast sides | non-role breakfast-side items (breakfast, fruit, dairy, milk drink, yoghurt) ≥ 2 × breakfasts; with breakfasts, protein + carb + side servings ≥ the sum of all three needs, so bread and eggs count once |
| Variety (food group) | when a role needs > 4 units, one `substitution_group` supplies ≤ 40 % protein / 50 % carb / 40 % veg (but at least one pack, and never less than a pinned `min_qty`) |
| Variety (product) | per-product upper bound ⌈35 % × need / role units⌉ when need > 4, else ⌈need / role units⌉; non-role items ≤ 2 |
| Integrality | packs are whole numbers ≥ 0 (or ≥ `min_qty`) |
| Time limit | `SOLVER_TIMEOUT_MS` (default 5000) via HiGHS |

Requirements are evaluated **after** `strategy.adjust`.

## 4. Result schema — `OptimisationResult`

| Field | Meaning |
|---|---|
| `feasible` | a basket was found |
| `items` | `[(Candidate, packs)]`, packs > 0 |
| `total` | Σ price × packs, 2 dp |
| `nutrition` | totals for `kcal, protein_g, carbs_g, fat_g, fibre_g, veg_serves` |
| `metrics` | `surplus_servings`, `prep_minutes`, `objective` |
| `message` | reason when not feasible (see below) |
| `solver_ms` | wall time |
| `requirements` | the requirements after `adjust` |
| `timed_out` | the solver hit its time limit |

`feasible=False` messages:

| `message` | `timed_out` | Meaning — caller must |
|---|---|---|
| `No basket satisfies every constraint.` | false | genuinely infeasible → UC-03 negotiation |
| `Timed out before finding a basket.` | **true** | **not** proof of infeasibility (UC-02 ext 2b/3b) → report the timeout and offer a retry; never start negotiation |
| `No priced, compliant products to choose from.` | false | data failure → report missing data |
| `A required product is unavailable or excluded.` / `Product quantities must be non-negative whole numbers.` / `Minimum quantity exceeds the maximum for a product.` | false | invalid pins from an edit → reject the edit, keep the basket |

## 5. Infeasible-result schema (handed to UC-03)

When the confirmed request is infeasible, `workflows/negotiation.analyse` returns:

```json
{
  "message": "LLM text from the negotiation_message task (facts only)",
  "options": [
    {"id": "increase_budget", "label": "Increase budget to $7.00", "detail": "+$2.00, everything else unchanged", "budget": 7.0},
    {"id": "reduce_days", "label": "Cover 5 days instead of 7", "detail": "10 meals per person within $5.00", "days": 5}
  ],
  "blocked_roles": [],
  "budget": 5.0,
  "days": 7,
  "person_meals": 14,
  "shortfall": 2.0
}
```

- **Minimum budget** = the Lowest Cost solve of `strategy.adjust(req)` (the shopper's own goal's bar)
  with `enforce_budget=False`, rounded **up** to the cent. Offered only when it exceeds the budget.
- **Maximum feasible meals** = the largest whole number of days `d < days` whose
  `Requirements.from_constraints(cs, days=d)` is feasible under the shopper's strategy at the current budget.
- **`blocked_roles`**: when even the uncapped solve fails, the roles (`protein`, `carb`, `veg`) with no
  compliant candidate; no budget option is offered.
- `shortfall` = minimum budget − budget, or `null`.
- Restrictions and preferences are never an option; a chosen option changes only `budget` or `days`, and
  the basket is re-solved only after the shopper confirms (`POST /sessions/{id}/negotiate`).

## 6. Fixtures and known answers

One retailer, six products (each tagged with its recipe ingredient, so it fills its role), one person, two main meals: kcal 1100, protein 44 g, veg 4 serves, 2 protein and
2 carb servings. Every need is ≤ 4, so variety caps are inactive and each pack's upper bound is 1.

| Product | Role | Price | kcal | Protein g | Veg serves |
|---|---|---|---|---|---|
| Chicken thigh | protein (2 serv.) | 6.00 | 600 | 50 | 0 |
| Brown lentils | protein (2 serv.) | 2.00 | 400 | 18 | 0 |
| Rice | carb (4 serv.) | 3.50 | 1400 | 25 | 0 |
| Penne | carb (4 serv.) | 2.00 | 1400 | 20 | 0 |
| Broccoli | veg | 3.00 | 120 | 10 | 4 |
| Carrots | veg | 2.00 | 100 | 3 | 4 |

| Case | Goal | Budget | Expected |
|---|---|---|---|
| `feasible_lowest_cost` | Lowest cost | $10 | lentils + penne + broccoli, **$7.00** (lentils + penne + carrots is $6 but only 41 g protein) |
| `infeasible_budget` | Lowest cost | $5 | infeasible, not timed out; min budget **$7.00**, shortfall $2.00 |
| `infeasible_budget_best_nutrition` | Best nutrition | $8 | infeasible; the goal's bar (6.4 veg, 48.4 g protein) needs both vegetables: min budget **$9.00** |
| `infeasible_no_protein` | Lowest cost | $50 | infeasible with no protein products; no budget fixes it |
| `every_goal_feasible` | all five | $20 | feasible, within budget, meets `adjust`ed targets, identical on repeat |
| (monkeypatched timeout) | — | — | `feasible=false`, `timed_out=true`, timeout message |

## 7. Hand-over

The production optimiser stays with S03. Changes to coefficients, constraint rows or the result schema
must keep `tests/test_optimiser_contract.py` green or update this page and the fixtures in the same PR.
Consumers of `timed_out` (UC-02 build and UC-03 negotiation) are wired up in P03.
