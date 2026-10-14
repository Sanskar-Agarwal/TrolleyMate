# Team guide — who owns what, and how we work

The code is split along the same lines as our Stage 1 contribution table: each person owns
the ad-hoc requirements (1.2.x) they specified, end to end — agent logic, API, UI and tests.
Every area already works in a basic form; your job is to **deepen** it, not start it.

## 1. Ownership

| Member | Area | Stage 1 requirements | Use cases | Agent |
|---|---|---|---|---|
| **Sanskar** | Intake & optimisation | 1.2.1–1.2.3 | UC-01, UC-02, UC-08 | Personal Shopper (intake + basket) |
| **Peter** | Negotiation, substitution & buy-timing | 1.2.4–1.2.6 | UC-03, UC-04 | Personal Shopper (trade-offs) |
| **Chester** | Pricing & conversational editing | 1.2.7–1.2.9 | UC-05, UC-09 | Market Analyst |
| **Reyon** | Compliance, nutrition & preferences | 1.2.10–1.2.12 | UC-06 | Nutrition & Compliance |
| **Maaz** | Platform, governance & human review | 1.2.13–1.2.15 | UC-07, UC-10, UC-06 ext | Technical Manager |

Maaz is also **integration lead**: CI/CD, Docker, deployment, merging, release tags, demo script.

### Files each person owns

| | Backend (`backend/app/…`) | LLM tasks (`llm/tasks/…`) | Frontend (`frontend/src/features/…`) |
|---|---|---|---|
| Sanskar | `workflows/intake.py`, `workflows/basket_builder.py`, `workflows/meal_planning.py`, `optimisation/*`, `services/meal_planner.py`, `api/intake.py`, `api/baskets.py`, `api/meal_plans.py`, `seed/recipes.json` | `extract_constraints`, `meal_plan_notes`, `classify_intent` | `intake/`, `basket/`, `mealplan/`, `shop/` |
| Peter | `workflows/negotiation.py`, `workflows/substitution.py`, `services/buy_timing.py`, `api/substitutions.py` | `tradeoff`, `negotiation_message` | `negotiation/`, `substitution/`, `buytiming/` |
| Chester | `agents/market_analyst.py`, `services/pricing/*`, `workflows/basket_editing.py`, `api/pricing.py`, `api/editing.py`, `seed/catalogue.json` | `parse_edit`, `market_insight` | `pricing/` |
| Reyon | `agents/nutrition_compliance.py`, `services/dietary_rules.py`, `api/compliance.py`, `api/preferences.py` | `assess_ingredient` | `compliance/`, `preferences/` |
| Maaz | `core/*`, `main.py`, `agents/base.py`, `agents/context.py`, `agents/technical_manager.py`, `workflows/escalation.py`, `api/auth.py`, `api/households.py`, `api/escalations.py`, `api/audit.py`, `api/system.py`, `llm/service.py`, `llm/providers.py`, `domain/*` | `explain`, `supply_information`, `chat_reply` | `profile/`, `review/`, `admin/`, `explain/`, `components/`, `auth/` |

`.github/CODEOWNERS` encodes this so the right person is asked to review automatically —
**put everyone's GitHub username into it** (placeholders are `@SANSKAR_GITHUB` etc.).

### Shared files — coordinate before editing

These are touched by everyone, so keep edits small and in your own section:

- `frontend/src/api/endpoints.ts` and `frontend/src/api/types.ts` — grouped by owner with comment headers
- `backend/app/api/common.py` — serializers (change a shape → update `types.ts` in the same PR)
- `backend/app/domain/*` — schema changes: tell the team, then everyone runs `python -m app.seed --reset`
- `backend/app/api/__init__.py`, `frontend/src/App.tsx` — routers/routes are already registered; you shouldn't need to touch them

## 2. Backlog to start Sprint 1 with

Copy these into Jira as stories (`As a … I want … so that …`, MoSCoW label, definition of done).
**M** = must for the demo, **S** = should, **C** = could.

**Sanskar — Intake & optimisation**
- M: Tune the `extract_constraints` prompt on the Campus Qwen model; add 15–20 real requests as a test set (`tests/test_intake.py`).
- M: Improve the structured-form mode UI (edit restrictions/preferences, not just numbers).
- S: Portion factors by age group (child ≈ 0.6 serve) in `Requirements.from_constraints`.
- S: Make the optimiser recipe-aware so meal plans cover every meal (e.g. add "can form N recipes" constraints).
- C: LLM-written recipe steps on each meal card.

**Peter — Negotiation, substitution & buy-timing**
- M: More trade-off types in `negotiation.analyse` (e.g. lower the protein target, drop to standard instead of organic).
- M: Substitution shows the top 3 candidates, not just one; proactive out-of-stock flags.
- S: Price-history chart on the "When to buy" tab (endpoint already exists: `GET /api/products/{id}/history`).
- C: Better timing model (moving average / day-of-week regression with a confidence score).

**Chester — Pricing & conversational editing**
- M: Real data ingestion: a CSV/JSON importer or a scraper behind `PartnerApiAdapter` (keep the `PriceSource` interface).
- M: Flag products whose unit price can't be normalised in the comparison UI (1.2.7).
- S: Before/after diff when a chat edit changes the basket.
- S: "Why is X cheaper at Y?" chat intent using `MarketAnalystAgent.explain_difference`.

**Reyon — Compliance, nutrition & preferences**
- M: Grow the ingredient/allergen knowledge base (E-numbers, more composites) in `catalogue.json`; tests for each cascade.
- M: "Accept this nutritional exception" flow (1.2.11 lets a shopper accept a gap explicitly).
- S: Learn preferences from declined substitutions (`Preference.source = "learned"`).
- C: Retrieval-augmented `assess_ingredient` over FSANZ allergen guidance (RAG — good for the advanced-tech marks).

**Maaz — Platform, governance & human review**
- M: Configure the Campus Qwen proxy in `.env`; run the whole demo on it; record which prompts misbehave.
- M: Deploy (Render/Railway/Azure/AWS) from CI; Postgres option; branch protection; Jira ↔ GitHub link.
- S: Notifications when a case is resolved (toast in the shopper UI); founder can reassign cases.
- S: Audit dashboard charts (decisions per agent, fallback rate, confidence distribution).
- C: Edit the household profile from the chat ("Jamie is now vegetarian").

## 3. Git workflow

We use **short-lived feature branches off `main`**, merged by pull request. No long-lived
per-person branches — they drift and cause painful merges.

### One-time setup (each teammate)

```bash
git clone https://github.com/rkn321/ELEC5620-Group5-TrolleyMate.git
```

Then run `scripts/setup.ps1` (Windows) or `scripts/setup.sh` (macOS/Linux). See the README.

### Repo owner, one time (GitHub → Settings → Branches → Add rule for `main`)

- Require a pull request before merging, with **1 approval**
- Require status checks to pass: `backend`, `frontend`
- Do not allow force pushes

Also connect Jira: Jira → Apps → **GitHub for Jira** → add the repo. Any branch, commit or PR
containing an issue key (e.g. `TM-12`) then shows up on that Jira ticket — this is our evidence
of iterative development for the Agile criterion.

### Every piece of work

```bash
git switch main
git pull
git switch -c feat/TM-12-substitution-top-three
```

Branch names: `<type>/<JIRA-KEY>-<short-description>`, where type is `feat`, `fix`, `chore`,
`docs` or `test`.

Commit early, with the Jira key first:

```bash
git add -A
git commit -m "TM-12: show top three substitute candidates"
git push -u origin feat/TM-12-substitution-top-three
```

Open a PR (GitHub UI, or `gh pr create --fill`). CI runs tests, lint, build and a Docker smoke
test. The area owner reviews (auto-requested via CODEOWNERS). **Squash and merge**, then delete
the branch.

Keep your branch current while you work:

```bash
git fetch origin
git rebase origin/main
git push --force-with-lease
```

### Definition of done

1. `pytest` and `npm run build` pass locally and in CI
2. New behaviour has at least one test (backend) or was clicked through in the browser (frontend)
3. Works with `LLM_PROVIDER=mock` **and** has been tried once with the real LLM if prompts changed
4. Agent decisions are logged through `agent.log(...)` so they appear in the audit log
5. PR approved and merged; Jira ticket moved to Done

### Sprints (to the 1 November code deadline)

| Sprint | Dates | Goal |
|---|---|---|
| 1 | 14–20 Oct | Everyone deepens their area's **M** stories; real LLM working end to end |
| 2 | 21–27 Oct | **S** stories; deployed URL; demo script dry run |
| 3 | 28 Oct–1 Nov | Bug fixes only, final tag `v1.0`, zip uploaded to Canvas |

At each sprint end: review + retro (screenshot the Jira board), then tag:

```bash
git switch main && git pull
git tag sprint-1
git push origin sprint-1
```

## 4. Conventions

- **Agents decide, services compute.** Judgement (interpreting text, explaining, judging vague
  ingredients) goes through `agent.think("<task>", ctx)`. Arithmetic, optimisation and lookups
  are plain Python. This is the split we justified in Stage 1 §4.1 — keep it.
- **Every LLM task has a mock.** New task = new file in `backend/app/llm/tasks/` with `SYSTEM`,
  `build_user`, `mock`, optional `SCHEMA`; register it in `tasks/__init__.py`. The mock keeps
  tests and the demo working offline.
- **Never relax a mandatory restriction.** Compliance filters candidates *before* the optimiser
  sees them. Uncertain items are withheld and escalated, never shown as safe.
- **Log significant decisions** with `self.log(action, decision, rationale=…, confidence=…, llm=result)`.
- Python: `ruff check app tests` must pass. TypeScript: `strict` mode, no `any`.
