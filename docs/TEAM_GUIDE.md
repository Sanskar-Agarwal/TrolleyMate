# Team guide — who owns what, and how we work

The code is split along the same lines as our Stage 1 contribution table: each person owns
the ad-hoc requirements (1.2.x) they specified, end to end — agent logic, API, UI and tests.
Use this guide for ownership and working conventions. For the current verified implementation,
see [README verification](../README.md#verification); for presentation and human release gates,
see [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). Ownership describes responsibility, not proof
of an individual's completed contribution or agreement.

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

`.github/CODEOWNERS` routes reviews to the configured GitHub owners. Peter's area currently
falls back to the default owner; request Peter's review explicitly where appropriate.

### Shared files — coordinate before editing

These are touched by everyone, so keep edits small and in your own section:

- `frontend/src/api/endpoints.ts` and `frontend/src/api/types.ts` — grouped by owner with comment headers
- `backend/app/api/common.py` — serializers (change a shape → update `types.ts` in the same PR)
- `backend/app/domain/*` — coordinate schema changes and data updates. There are no migrations;
  reset only a disposable development database after preserving any data that must be retained.
- `backend/app/api/__init__.py`, `frontend/src/App.tsx` — routers/routes are already registered; you shouldn't need to touch them

## 2. Delivery scope and remaining work

The original Sprint 1 suggestions mixed the Stage 1 requirements with extensions labelled
Must/Should/Could. They are not a current list of unfinished requirements. Use Stage 1
**1.2.1–1.2.15**, the accepted Jira criteria and the release checklist as the acceptance baseline.

As of the 29 October integration:

| Area | Implemented and evidenced | Boundaries or separate follow-up |
|---|---|---|
| Intake and optimisation | Editable dietary/preferences forms, five goals, age-based default portions, accepted-stock meal allocation, explicit gaps and cancellation | Full joint recipe/basket optimisation and generated cooking instructions remain extensions; live prompt checks must identify the model actually used |
| Negotiation, substitution and timing | Budget/coverage options, one safe substitute with accept/decline, remembered declines, history-based timing | Top-three alternatives, extra trade-off types, proactive stock alerts and price-history charts remain extensions; KAN-11 still needs its complete failure-evidence matrix |
| Pricing and editing | CSV/JSON importer, optional HTTP partner adapter, unit-price warnings, edit change summaries and price-question chat | Bundled prices/history are demonstration data; a real retailer connection needs its own data and verification |
| Compliance and preferences | Composite/label screening, withheld uncertainty, nutrition-exception flow, learned preferences and retrieved allergen guidance | Knowledge-base and model limits are documented in the safety evaluation; these are prototype checks |
| Platform and review | Shopper registration, profiles, reviewer reassignment, explanations/audit, household chat changes, Docker and GHCR publication | Hosting is separate from image publication; audit charts and automatic shopper review notifications remain extensions |

The outstanding Jira work includes Peter's KAN-11 failure-path evidence and KAN-12 recovery
demo/three-iteration retrospective/contribution, Chester's KAN-18 process exports and contribution
links, and Maaz's KAN-30 exact submission package, contribution form and extract/run evidence.
Confirm current Jira details when planning work; this dated summary does not change ticket status.
KAN-6 is marked Done in Jira, but the repository does not contain a completed all-member rehearsal
or release agreement. The [release checklist](RELEASE_CHECKLIST.md) keeps those records unverified.

## 3. Git workflow

Prefer **short-lived feature branches off `main`**, merged by pull request. Existing member
branches have also been used; check the actual source and target before opening or merging a PR.

### One-time setup (each teammate)

```bash
git clone https://github.com/rkn321/ELEC5620-Group5-TrolleyMate.git
```

Then run `scripts/setup.ps1` (Windows) or `scripts/setup.sh` (macOS/Linux). See the README.

### Repository settings to verify

The following are intended controls, not proof that the remote settings are enabled:

- Require a pull request before merging, with **1 approval**
- Require the current backend, frontend and Docker CI checks to pass
- Do not allow force pushes

Also connect Jira: Jira → Apps → **GitHub for Jira** → add the repo. Any branch, commit or PR
containing a valid issue key (e.g. `KAN-11`) can then appear on that Jira ticket. Keep actual
review dates, feedback and scope changes alongside these links as iterative-development evidence.

### Every piece of work

```bash
git switch main
git pull
git switch -c test/KAN-11-failure-paths
```

Branch names: `<type>/<JIRA-KEY>-<short-description>`, where type is `feat`, `fix`, `chore`,
`docs` or `test`.

Commit early, with the Jira key first:

```bash
git add -A
git commit -m "KAN-11: verify substitution failure paths"
git push -u origin test/KAN-11-failure-paths
```

Open a PR (GitHub UI, or `gh pr create --fill`). CI runs tests, lint, build and a Docker smoke
test. Request the area owner's review, including an explicit request where CODEOWNERS falls
back to the default owner. Use the team's agreed merge method and remove a feature branch only
after its work is merged and it is no longer needed. Main pushes also publish the tested Docker
image; pull requests do not publish. See [CI_CD.md](CI_CD.md).

For a branch you alone own, keep it current while you work. Coordinate before rewriting any
shared branch history:

```bash
git fetch origin
git rebase origin/main
git push --force-with-lease
```

### Definition of done

1. Backend `pytest`/Ruff and frontend `npm test`/`npm run build` pass; required CI checks pass
2. New behaviour has at least one test (backend) or was clicked through in the browser (frontend)
3. Works with `LLM_PROVIDER=mock` **and** has been tried once with the real LLM if prompts changed
4. Agent decisions are logged through `agent.log(...)` so they appear in the audit log
5. PR reviewed and merged; Jira acceptance evidence linked before marking Done. Rehearsal,
   retrospectives, contributions and release agreement need their own genuine records.

### Original sprint plan (to the 1 November code deadline)

This was the planned schedule; it does not record completed reviews, hosting, tags or submission.
The delivery scope now uses a published Docker image rather than a promised hosted URL.

| Sprint | Dates | Goal |
|---|---|---|
| 1 | 14–20 Oct | Everyone deepens their area's **M** stories; real LLM working end to end |
| 2 | 21–27 Oct | **S** stories; deployed URL; demo script dry run |
| 3 | 28 Oct–1 Nov | Bug fixes only, final tag `v1.0`, zip uploaded to Canvas |

Record each actual review and retrospective with its date, participants, decisions and Jira
export. Create tags against the agreed commit only when the corresponding milestone is real;
do not backdate records or create historical tags as a substitute for missing review evidence.

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
