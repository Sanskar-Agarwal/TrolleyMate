# Trolley Mate — ELEC5620 Group 5

A grocery-planning prototype that turns a household's budget, meal needs and dietary
restrictions into an itemised basket. AI agents coordinate deterministic pricing,
optimisation and dietary checks, with human review for unresolved ingredient uncertainty.

**Stack:** React + TypeScript (Vite), FastAPI, SQLAlchemy/SQLite, SciPy MILP and configurable
hosted or local language models.

## What the prototype does

- Interprets natural-language requests, asks for clarification and activates constraints
  only after confirmation. The third correction switches to a structured form.
- Optimises for lowest cost, best nutrition, least waste, fastest cooking or a balanced
  goal. Infeasible requests lead to options the shopper must confirm.
- Compares retailer offers and unit prices, reports savings against a named baseline,
  flags stale or missing prices and uses recorded history for buying-time suggestions.
- Supports conversational basket edits and proposed substitutions with explicit acceptance
  or rejection, while retaining mandatory dietary restrictions.
- Checks nested ingredients and nutrition, withholds uncertain items and routes unresolved
  cases to an authorised human reviewer.
- Builds quantity-limited meal plans from accepted baskets, showing pantry reuse and gaps.
- Maintains household profiles, editable preferences and explanations with audit records.

Catalogue data, prices and accounts are demonstration fixtures; see the
[data provenance](backend/app/seed/PROVENANCE.md). Outcomes depend on available evidence,
rules and model responses. The [compliance guide](docs/COMPLIANCE_VERDICT.md) and
[optimisation guide](docs/OPTIMISATION_AND_MEALS.md) describe the implementation's limits.

## Agent roles

| Agent | Role | Responsibility |
|---|---|---|
| Personal Shopper | Supervisor | Request interpretation, confirmed constraints and coordination of baskets, edits, substitutions and meals |
| Market Analyst | Worker | Retailer offers, unit prices, freshness, savings and buying-time advice |
| Nutrition & Compliance | Worker | Dietary and nutritional checks, uncertainty and review escalation |
| Technical Manager | Additional governance role | Decision explanations and independent audit oversight outside the supervisor–worker chain |

The dietitian is a human review role. See [architecture](docs/ARCHITECTURE.md) for the
component boundaries and the [team guide](docs/TEAM_GUIDE.md) for ownership and workflow.

## Quick start

Run these commands from the repository root. Use Python **3.12** and Node **20.19+ (20.x),
22.12+ (22.x), or 24+**. CI uses Python 3.12 and Node 22. Initial installation needs network
access to download dependencies; the default mock mode needs no AI key.

**macOS / Linux**

```bash
./scripts/setup.sh
./scripts/dev.sh
```

**Windows (PowerShell)**

```powershell
.\scripts\setup.ps1
.\scripts\dev.ps1
```

Open [the app](http://localhost:5173). API documentation is at
[localhost:8000/docs](http://localhost:8000/docs). Setup creates `.env` only when it is
missing and preserves existing configuration and database contents.

| Demo account | Role | Starting scenario |
|---|---|---|
| `alex@trolleymate.demo` | Shopper | Household with lactose intolerance and a tree-nut allergy |
| `riley@trolleymate.demo` | Shopper | Single person with no initial restrictions |
| `sam@trolleymate.demo` | Dietitian | Review items the agents could not clear |
| `maya@trolleymate.demo` | Founder | Inspect agent decisions and audit records |

All demo accounts use `demo1234`. New shoppers can also register. The
[release checklist](docs/RELEASE_CHECKLIST.md) includes the current seven-minute demo route.

## Run with Docker

Build locally, including on Apple Silicon:

```bash
docker compose up --build
```

Open [localhost:8000](http://localhost:8000). The container serves the compiled React app
and API together. Compose reads the optional root `.env` and keeps data in a named volume.

To run the published GitHub Container Registry image in mock mode:

```bash
docker pull --platform linux/amd64 ghcr.io/rkn321/elec5620-group5-trolleymate:latest
docker run --detach --name trolleymate --platform linux/amd64 --publish 127.0.0.1:8000:8000 --env LLM_PROVIDER=mock --volume trolleymate-data:/data ghcr.io/rkn321/elec5620-group5-trolleymate:latest
```

Published images target `linux/amd64`; ARM64 machines need emulation or the local Compose
build. Private packages require registry authentication. Use a `sha-<full-commit-SHA>` tag
for a fixed release. [CI and container releases](docs/CI_CD.md) covers authentication,
updates and rollback. The pipeline publishes an image; it does not provision a hosted service.

Normal startup preserves existing data and does not update an already-seeded catalogue.
Use a fresh disposable database to try changed fixtures. See [deployment](docs/DEPLOYMENT.md)
for storage, Docker networking and explicitly destructive reset instructions.

## Configure a language model

The default `LLM_PROVIDER=mock` runs without an AI key. Edit the root `.env` using
[`.env.example`](.env.example) as a reference. For example, to use Groq:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=<model-available-to-your-account>
LLM_API_KEY=<your-key>
LLM_FALLBACK_TO_MOCK=true
```

| Provider | Configuration |
|---|---|
| Groq or another OpenAI-compatible service | `openai_compatible`, the service's base URL, an available model ID and its API key |
| ELEC5620 Campus Qwen proxy | `openai_compatible`; use the base URL, model and key from the Lab 9 proxy guide and the required university VPN |
| OpenAI | `openai_compatible`, `https://api.openai.com/v1`, an available model ID and API key |
| Local Ollama | `openai_compatible`, `http://localhost:11434/v1` and a downloaded model; see the deployment guide for container-to-host networking |
| Anthropic | `anthropic`, `ANTHROPIC_API_KEY` and an explicit `LLM_MODEL` available to the account |

Restart the backend after changes. The top-bar badge reflects configuration and recorded
fallback state; it is not proof that a live request succeeded. Check an actual agent call
and its audit entry when verifying a provider. Calls use bounded retries and can fall back
to labelled offline responses. A fallback cannot clear an uncertain ingredient that needs
a live assessment; see the compliance guide for the distinction between intentional mock
mode and provider failure. Never commit `.env`, API keys, signing keys or local databases.

## Development checks

Run from the repository root after setup.

**macOS / Linux**

```bash
cd backend
source .venv/bin/activate
python -m ruff check app tests
python -m pytest
cd ../frontend
npm test
npm run build
```

**Windows (PowerShell)**

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m ruff check app tests
python -m pytest
cd ..\frontend
npm test
npm run build
```

[`scripts/verify_clean.py`](scripts/verify_clean.py) installs fresh dependencies, runs the
checks and exercises startup and provider-failure recovery from a clean source copy.
See the deployment guide for prerequisites and archive verification.

## Verification

The application baseline on **29 October 2026** is
[`947a59c`](https://github.com/rkn321/ELEC5620-Group5-TrolleyMate/commit/947a59cc6d94a9aec08c8ba5c55458b8b39eabf7),
integrated through [PR #14](https://github.com/rkn321/ELEC5620-Group5-TrolleyMate/pull/14).

| Check | Recorded result |
|---|---|
| Backend | 416 tests passed; Ruff passed |
| Frontend | 57 tests passed; TypeScript and production build passed |
| Local Docker (`linux/arm64`) | Fresh-database startup and basket checks passed, including allergy-change handling, quantity increases, cancellation and ownership |
| Main CI and GHCR (`linux/amd64`) | All jobs passed and the image was published in [run 40806441408](https://github.com/rkn321/ELEC5620-Group5-TrolleyMate/actions/runs/40806441408) |

The backend total includes the fixed 42-case agent evaluation and two additional
integration regressions for basket extras. The [full browser UAT](docs/UAT_2026-10-28.md)
is a dated 28 October record and was not repeated in full for PR #14. Technical checks do
not establish that a group rehearsal, contribution agreement or release approval happened;
those human gates remain explicit in the release checklist.

## Documentation and source map

| Topic | Documents |
|---|---|
| Design and interfaces | [Architecture](docs/ARCHITECTURE.md), [API contracts](docs/API_CONTRACTS.md) |
| Team and decisions | [Team guide](docs/TEAM_GUIDE.md), [decision log](docs/DECISIONS.md) |
| Feature behaviour | [Optimisation and meals](docs/OPTIMISATION_AND_MEALS.md), [compliance](docs/COMPLIANCE_VERDICT.md) |
| Running and releasing | [Deployment](docs/DEPLOYMENT.md), [CI/CD](docs/CI_CD.md), [release checklist](docs/RELEASE_CHECKLIST.md), [submission checklist](docs/SUBMISSION_CHECKLIST.md) |
| Dated evidence | [Journey verification](docs/JOURNEY_VERIFICATION.md), [browser UAT](docs/UAT_2026-10-28.md), [agent evaluation](docs/evidence/agent-evaluation.md) |
| Demo data | [Seed provenance](backend/app/seed/PROVENANCE.md) |

```text
backend/app/
  agents/        four agents and per-request context
  workflows/     use-case orchestration
  optimisation/  MILP basket optimiser and goal strategies
  services/      pricing, meal planning, buying-time and dietary rules
  llm/           provider adapters, prompts, schemas and offline responses
  domain/        SQLAlchemy domain models
  api/           FastAPI feature routes
  seed/          demo catalogue, recipes and accounts
backend/tests/   service, API, safety and agent regression tests
frontend/src/    React features, shared components and typed API client
scripts/         setup, development and clean-copy verification
docs/           design, operation and assessment evidence
```
