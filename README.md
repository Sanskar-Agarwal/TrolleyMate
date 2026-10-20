check /docs for work split.  -maaz

# Trolley Mate — ELEC5620 Group 5

An AI-native grocery personal shopper. Tell it your budget, meals and allergies in plain
English; four cooperating agents build a basket that is **safe, in budget and explained**, with
a registered dietitian in the loop for anything the AI can't confirm.

- **Stack:** React + TypeScript (Vite) · FastAPI · SQLAlchemy/SQLite · SciPy MILP optimiser · pluggable LLM (Campus Qwen, any OpenAI-compatible server, local Ollama, or Claude)
- **Architecture:** Supervisor–Worker agents with deterministic services and a human approval gate — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Team split & git workflow:** [docs/TEAM_GUIDE.md](docs/TEAM_GUIDE.md)
- **Demo walkthrough:** [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)
- **CI and container releases:** [docs/CI_CD.md](docs/CI_CD.md)

## Quick start

Needs Python 3.11+ and Node 22.12+ (Node 24 also works).

**Windows (PowerShell)**

```powershell
.\scripts\setup.ps1
.\scripts\dev.ps1
```

**macOS / Linux**

```bash
./scripts/setup.sh
./scripts/dev.sh
```

Open http://localhost:5173 and click a demo account (password `demo1234` for all):

| Account | Role | Use it to |
|---|---|---|
| `alex@trolleymate.demo` | Shopper | Household with a lactose intolerance and a tree-nut allergy |
| `riley@trolleymate.demo` | Shopper | Single person, no restrictions |
| `sam@trolleymate.demo` | Dietitian | Review items the AI couldn't certify |
| `maya@trolleymate.demo` | Founder | Audit every agent decision |

API docs: http://localhost:8000/docs

**Docker (build locally)**

```bash
docker compose up --build
```

Then open http://localhost:8000.

**Ready-to-run Docker image**

After a successful publish job on `main`, the image is available from GitHub Container
Registry. Check the [CI workflow](https://github.com/rkn321/ELEC5620-Group5-TrolleyMate/actions/workflows/ci.yml)
for publication status; adding the workflow does not itself publish an image.

```bash
docker pull --platform linux/amd64 ghcr.io/rkn321/elec5620-group5-trolleymate:latest
docker run --detach --name trolleymate --platform linux/amd64 --publish 127.0.0.1:8000:8000 --env LLM_PROVIDER=mock --volume trolleymate-data:/data ghcr.io/rkn321/elec5620-group5-trolleymate:latest
```

Open http://localhost:8000. This runs the demo locally with persistent data and no LLM key.
Published images target `linux/amd64`; Apple Silicon and other ARM64 machines need amd64
emulation, or can use the local Compose build above. Private packages require a GitHub login.
See [CI and container releases](docs/CI_CD.md) for authentication, pinned versions, updates
and rollback. The pipeline publishes an image; hosting is a separate step.

## Connecting a real LLM

With no configuration the agents run in **offline mode** — every LLM task has a rule-based
mock, so the app, tests and CI work without keys. To use a real model, copy `.env.example` to
`.env` and pick one:

| Provider | Settings |
|---|---|
| ELEC5620 Campus Qwen proxy (uni VPN) | `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` from the Lab 9 proxy guide |
| OpenAI | `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL=https://api.openai.com/v1`, `LLM_MODEL`, `LLM_API_KEY` |
| Local model (Ollama) | `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL=http://localhost:11434/v1`, `LLM_MODEL=qwen2.5:7b` |
| Anthropic Claude | `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, optional `LLM_MODEL` (default `claude-opus-5-5`) |

Restart the backend after editing `.env`. The badge in the top bar shows the active model, and
turns amber if calls are falling back to the offline mock. **Never commit `.env`** — it's git-ignored.

## Project layout

```
backend/app/
  agents/        the four agents + per-request AgentContext
  workflows/     one module per use case (UC-01 … UC-09)
  optimisation/  BasketOptimiser (MILP) + goal strategies
  services/      deterministic services: pricing, buy-timing, meal planner, dietary rules
  llm/           LLMService, providers, and one file per LLM task (prompt + schema + mock)
  domain/        SQLAlchemy models, organised by the Stage 1 package diagram
  api/           FastAPI routers, one per feature
  seed/          demo catalogue, recipes, accounts
frontend/src/
  features/      one folder per feature (intake, basket, pricing, review, …)
  components/    shared UI (agent activity feed, shelf tag, drawer)
  api/           typed client for every endpoint
docs/            architecture, team guide, demo script
```

## Common commands

```bash
cd backend
.venv/Scripts/python -m pytest              # tests (macOS/Linux: .venv/bin/python)
.venv/Scripts/ruff check app tests          # lint
.venv/Scripts/python -m app.seed --reset    # wipe and reload demo data

cd frontend
npm run dev                                 # dev server with /api proxy
npm test                                    # React component regression tests
npm run build                               # typecheck + production build
```
