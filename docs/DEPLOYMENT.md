# Deploying Trolley Mate

How to build and run the prototype from a fresh copy of the source (for example the Canvas zip on
the Week 13 demo machine), what to configure, how to tell which AI mode is running, and what to do
when something goes wrong. Owner: Maaz (KAN-29). CI and image publishing: see [CI_CD.md](CI_CD.md).

## What you need

| | Version | Check |
|---|---|---|
| Python | 3.12 or newer (3.12 in Docker) | `python --version` |
| Node.js | 20.19+ (20.x), 22.12+ (22.x), or 24+ (22 in CI) | `node --version` |
| Docker (optional) | Compose v2.24+ | `docker compose version` |

No AI key, database server or internet connection is needed to run the demo: the app ships with
seed data and an offline agent mode.

## Option A: Docker (one container)

```bash
docker compose up --build
```

Open http://localhost:8000. Data lives in the `trolleymate-data` volume; delete it with
`docker compose down -v` to start fresh.

## Option B: Without Docker

Windows (PowerShell):

```powershell
.\scripts\setup.ps1
.\scripts\dev.ps1
```

macOS / Linux:

```bash
./scripts/setup.sh
./scripts/dev.sh
```

Open http://localhost:5173. Setup installs **exact** versions: `backend/requirements.lock` for
Python and `frontend/package-lock.json` (via `npm ci`) for the frontend.

## Verify a clean build before you rely on it

```bash
python scripts/verify_clean.py                         # a clean copy of the current commit
python scripts/verify_clean.py --source release.zip    # the submission archive
```

It builds in an empty temp folder and checks, in order:

1. Pinned install with `pip check`
2. Backend tests and frontend tests
3. Production build
4. Server start with **no AI key**: health, the built UI, demo sign-in, and a full basket build
5. A second start with an **unreachable AI provider**, which must still build a basket with every AI step flagged as a fallback

A passing run ends with `PASSED`. The latest run is in [evidence/clean-deploy.log](evidence/clean-deploy.log).

## Configuration

Copy `.env.example` to `.env` (setup does this for you). Everything has a working default.

| Setting | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `mock`, `openai_compatible` (Campus Qwen proxy, OpenAI, Ollama) or `anthropic` |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | empty | For `openai_compatible`; the campus proxy needs the uni VPN |
| `ANTHROPIC_API_KEY` | empty | For `anthropic` |
| `LLM_FALLBACK_TO_MOCK` | `true` | Keep on for demos: a failed AI call is answered offline instead of erroring |
| `SECRET_KEY` | generated | Signs logins; generated into `backend/.secret_key` if unset |
| `DATABASE_URL` | `backend/trolleymate.db` | SQLite file; any SQLAlchemy URL works |

## Which AI mode is running?

The badge in the top bar (and `GET /api/system/llm`, field `mode`) always says:

| Mode | Badge | Meaning |
|---|---|---|
| `offline` | "Offline agent mode" | No provider chosen; every AI task uses its rule-based offline answer |
| `offline_unconfigured` | "Offline agent mode" (hover for the reason) | A provider was chosen but is missing settings, e.g. no `LLM_BASE_URL` |
| `live` | the model name, green | A real model is answering |
| `degraded` | the model name, amber, "· N fallbacks" | A real model is configured but some calls failed and were answered offline |

Each fallback is also marked in the agent activity feed (`LLM → fallback`) and in the audit log
(`model_version` ends in `(fallback)`), so no answer is ever passed off as coming from the model
when it didn't.

## Recovery

| Problem | Fix |
|---|---|
| Badge says `degraded`, or the campus proxy times out | Connect the uni VPN and check the key. The demo keeps working meanwhile. To go fully offline, set `LLM_PROVIDER=mock` and restart the backend. |
| Badge says `offline_unconfigured` | Hover the badge for the missing setting, fix `.env`, restart the backend |
| Wrong or messy demo data | `cd backend` then `.venv/Scripts/python -m app.seed --reset` (macOS/Linux: `.venv/bin/python`) |
| Errors after pulling teammates' changes (new tables or columns) | Same reset; there are no migrations |
| Everyone is signed out | `backend/.secret_key` was deleted or `SECRET_KEY` changed; sign in again |
| `Can't reach the Trolley Mate server` in the UI | The backend isn't running on port 8000; start it with `scripts/dev.*` |
| Port 8000 or 5173 already in use | Stop the other process, or run `uvicorn app.main:app --port 8001` and set `VITE_API_PROXY=http://127.0.0.1:8001` for the frontend |
| Frontend build errors about missing modules | `cd frontend && npm ci` (stale `node_modules`) |
| `pip` resolver errors | Reinstall from the lockfile: `pip install --no-deps -r requirements.lock` |
| Docker image won't start | `docker compose logs app`; reset data with `docker compose down -v` |
