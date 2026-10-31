# Trolley Mate — ELEC5620 Group 5

A grocery-planning prototype that turns a household's budget, meal needs and dietary
restrictions into an itemised basket. AI agents coordinate deterministic pricing,
optimisation and dietary checks, with human review for unresolved ingredient uncertainty.

**Stack:** React + TypeScript (Vite), FastAPI, SQLAlchemy/SQLite, SciPy MILP and configurable
hosted or local language models. Optional OpenTelemetry tracing exports to Jaeger.

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

## Marker setup: Campus Qwen (recommended for assessment)

The team used Groq during development and testing. Its connection settings are kept
**commented out in `.env.example`** as a reference; they are not campus-Qwen settings.
The submitted ZIP deliberately excludes `.env` and the team's API key. Please configure
your own credentials locally. With the example unchanged, the application runs in
`mock` mode; this is an offline fallback, not a live AI demonstration.

1. Extract the ZIP and open a terminal in the folder containing `docker-compose.yml`.
   Install and start Docker Desktop with Docker Compose v2.24 or later. The first build
   needs internet access to download images and dependencies.
2. Create your local configuration file (do not overwrite an existing `.env` containing
   credentials you want to keep):

   **macOS / Linux**
   ```bash
   cp .env.example .env
   ```

   **Windows PowerShell**
   ```powershell
   Copy-Item .env.example .env
   ```

3. Open `.env` in a text editor. Replace `LLM_PROVIDER=mock` with the following campus
   configuration, filling in the endpoint, model ID and key supplied in the ELEC5620
   campus-Qwen proxy connection guide. Replace the placeholders; do not paste them literally.
   Keep only one active assignment for each variable.

   ```dotenv
   LLM_PROVIDER=openai_compatible
   LLM_BASE_URL=<campus OpenAI-compatible base URL from the course guide>
   LLM_MODEL=<exact campus-Qwen model ID from the course guide>
   LLM_API_KEY=<your own campus-Qwen API key>
   LLM_FALLBACK_TO_MOCK=false
   ```

   Use the service's base URL, not a full `/chat/completions` URL. Do not reuse the
   commented Groq endpoint or Groq model ID for campus Qwen. Connect to the university
   network/VPN if required by the course guide. Disabling fallback for assessment makes
   provider failures visible instead of substituting offline responses.
4. Build and start the application and its trace dashboard:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.observability.yml up --build -d
   ```

   Open the application at **http://localhost:8000** and Jaeger at
   **http://localhost:16686**. Use a demo account from the table below; all use `demo1234`.
5. Verify a real AI request: sign in as `riley@trolleymate.demo` and submit a shopping
   request. Inspect its agent activity/audit record for a successful model call without
   fallback. The configured model badge alone does not prove a live call succeeded.
   For connection failures, check the campus endpoint, model ID, key and required VPN,
   then inspect `docker compose logs --tail=100 app`. The team tested Groq; a campus-Qwen
   connection must be verified with the marker's credentials and network access.

After changing `.env`, recreate the app container so it receives the new values:

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d --force-recreate app
```

Stop both containers while keeping saved database data:

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml stop
```

To start them again, run the `up --build -d` command above. Keep your real `.env` privately
on your laptop for the demonstration; do not include it in the submission or commit it.
For optional offline testing, set `LLM_PROVIDER=mock`; no API key is required.

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

## Optional observability

Use [OpenTelemetry and Jaeger](docs/OBSERVABILITY.md) to inspect API, agent, AI-call
and optimiser timings in a local trace dashboard. Tracing is disabled by default; the
guide includes a Docker Compose override and a short presentation demonstration.

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

The **30 October 2026** follow-up on `Sanskar` includes live Groq browser testing,
security controls and corrections to existing behaviour. See the
[current acceptance report](docs/UAT_LIVE_2026-10-30.md) and [security design](docs/SECURITY.md).

| Check | Recorded result |
|---|---|
| Backend | 530 tests passed; Ruff passed |
| Frontend | 62 tests passed; TypeScript and production Vite build passed |
| Local browser | Shopper intake, all five goals, cancellation, negotiation, substitutions, meals, household, human review and audit exercised |
| Live Groq | VPN-related 403 resolved; real model calls succeeded. Free-tier 429 responses still occurred and exercised labelled fallback |
| Security | Browser session eviction, sign-out everywhere, throttling and protected shopping flow passed; automated CSRF, password migration and expiry checks passed |
| Docker and hosted CI | Not rerun for these corrections; prior results below are historical |

The existing Groq key and model were used unchanged, with bounded output tokens and
Groq Qwen instruct mode. Passwords use salted PBKDF2-HMAC-SHA256 (600,000 iterations).
Login sessions expire after 30 minutes idle or eight hours absolute, with three concurrent
logins per account. Existing logins must sign in again after this upgrade. Configurable
rate limits and CSRF checks are described in the security guide.

Test data was isolated from existing application data. The browser scenarios are representative
acceptance coverage, not proof of every possible branch or production-security certification.

Historical evidence: the 29 October baseline passed 416 backend and 57 frontend tests,
local ARM64 Docker checks and [main CI/GHCR run 40806441408](https://github.com/rkn321/ELEC5620-Group5-TrolleyMate/actions/runs/40806441408).
Those results do not certify the latest branch or container image. Technical checks do not
establish a group rehearsal, contribution agreement, retrospective or submission upload;
those human gates remain explicit in the release checklist.

## Documentation and source map

| Topic | Documents |
|---|---|
| Design and interfaces | [Architecture](docs/ARCHITECTURE.md), [API contracts](docs/API_CONTRACTS.md) |
| Team and decisions | [Team guide](docs/TEAM_GUIDE.md), [decision log](docs/DECISIONS.md) |
| Feature behaviour | [Optimisation and meals](docs/OPTIMISATION_AND_MEALS.md), [compliance](docs/COMPLIANCE_VERDICT.md) |
| Running and releasing | [Deployment](docs/DEPLOYMENT.md), [CI/CD](docs/CI_CD.md), [release checklist](docs/RELEASE_CHECKLIST.md), [submission checklist](docs/SUBMISSION_CHECKLIST.md) |
| Dated evidence | [Journey verification](docs/JOURNEY_VERIFICATION.md), [current browser UAT](docs/UAT_LIVE_2026-10-30.md), [earlier UAT](docs/UAT_2026-10-28.md), [agent evaluation](docs/evidence/agent-evaluation.md) |
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
