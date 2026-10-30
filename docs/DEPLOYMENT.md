# Deploying Trolley Mate

Build and run the prototype from the repository or an extracted submission archive. Run the
commands below from the project root unless a section says otherwise. Owner: Maaz (KAN-29).
CI and image publishing: see [CI_CD.md](CI_CD.md).

## What you need

| | Version | Check |
|---|---|---|
| Python | 3.12 or newer (3.12 in Docker) | `python --version` |
| Node.js | 20.19+ (20.x), 22.12+ (22.x), or 24+ (22 in CI) | `node --version` |
| Docker (optional) | Compose v2.24+ | `docker compose version` |

Initial setup needs internet access to download dependencies or Docker images. Once installed,
the seeded demo runs offline with `LLM_PROVIDER=mock`; no model key or separate database server
is needed. The catalogue and accounts are synthetic demo data.

Use the provided single-process server commands. Basket-build cancellation is held in memory
and is not shared between multiple Uvicorn worker processes.

## Option A: Docker (one container)

```bash
docker compose up --build
```

Open http://localhost:8000. The image builds React and serves it with FastAPI on port 8000.
Compose reads an optional root `.env`; without one, the model provider is `mock`. If you already
have a `.env`, check its provider and database settings before starting.

The database is `/data/trolleymate.db` in a Compose-managed `trolleymate-data` volume. Stop with
`docker compose down` to retain it. See [Resetting demo data](#resetting-demo-data) before
removing volumes. For a prebuilt image, platform details and rollback instructions, see
[CI_CD.md](CI_CD.md#pull-and-run-locally).

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

Open http://localhost:5173; the API and its interactive docs are at http://localhost:8000/docs.
Setup creates `backend/.venv`, installs `requirements-dev.txt` (which includes the pinned runtime
lockfile and test tools), runs the seed command, and uses `npm ci` for the frontend. It creates
the root `.env` only when one does not already exist.

The development script starts both servers. Stop both before resetting data; on Windows they
run in separate PowerShell windows. Demo accounts use `demo1234`, and the sign-in page also
supports creating a shopper account with its own household.

## Verify a clean build before you rely on it

```bash
python scripts/verify_clean.py                         # committed HEAD, excluding uncommitted edits
python scripts/verify_clean.py --source release.zip    # the submission archive
```

It builds in an empty temp folder and checks, in order:

1. Pinned install with `pip check`
2. Backend tests and frontend tests
3. Production build
4. Server start with **no AI key**: health, the built UI, demo sign-in, and a full basket build
5. A second start with an **unreachable AI provider**, which must still build a basket with every AI step flagged as a fallback

A passing run ends with `PASSED`. This command performs fresh installs, so it also needs
internet access; the application checks themselves use mock or deliberately unreachable model
settings. Use `--source release.zip` to verify an extracted-source submission rather than your
local Git commit. It does not test a Docker image or a real model provider.

[evidence/clean-deploy.log](evidence/clean-deploy.log) is historical evidence for commit `665c941`,
not the latest source. The [current verification summary](../README.md#verification) records the
29 October 2026 baseline: 416 backend tests, 57 frontend tests, Ruff, TypeScript/Vite, and local
Docker checks on `linux/arm64`. Main `947a59c` also passed
[CI run 40806441408](https://github.com/rkn321/ELEC5620-Group5-TrolleyMate/actions/runs/40806441408),
including its Docker smoke test and GHCR publishing job. Keep dated evidence associated with
the revision and platform it actually tested.

## Configuration

Copy [`.env.example`](../.env.example) to `.env` when you want to override defaults (setup does
this for you). Process environment variables override env files; for a direct backend run,
`backend/.env`, if present, overrides the root `.env`. Restart the backend after changing settings;
for Compose, rerun `docker compose up -d` so changed container environment values are applied.

| Setting | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `mock`, `openai_compatible` (campus proxy, Groq, OpenAI or Ollama), or `anthropic` |
| `LLM_BASE_URL`, `LLM_MODEL` | empty | Both required for `openai_compatible`; use values available from your chosen provider |
| `LLM_API_KEY` | empty | Required by hosted providers that authenticate requests; a local Ollama normally needs no key |
| `ANTHROPIC_API_KEY` | empty | Used for `anthropic`; `LLM_API_KEY` is also accepted. Set `LLM_MODEL` explicitly to select your model |
| `LLM_FALLBACK_TO_MOCK` | `true` | Failed provider calls use an offline answer, marked as a fallback; this does not certify uncertain ingredients |
| `LLM_TIMEOUT_S` | `45` | Timeout for provider calls |
| `SECRET_KEY` | generated | Signs logins; generated into `backend/.secret_key` if unset |
| `DATABASE_URL` | local SQLite file in `backend/`; `/data/trolleymate.db` in Docker | SQLite is the tested configuration. Other database URLs require their drivers and separate validation |
| `SEED_ON_STARTUP` | `true` | Loads the demo dataset when the database has no users; it does not refresh an existing dataset |

The default provider is offline; no live model is selected automatically. The Anthropic adapter
currently defaults to `claude-opus-5-5` when `LLM_MODEL` is empty. Provider access and model
availability depend on your account; configuring a model is separate from verifying a successful
request.

For a model running on the host, a Docker container uses
`http://host.docker.internal:11434/v1`, not `localhost`. The optional Compose `local-llm` profile
provides an `ollama` service at `http://ollama:11434/v1`; download its model before relying on an
offline demo. Model examples are in `.env.example`.

## Which AI mode is running?

The badge in the top bar polls `GET /api/system/llm` every 20 seconds. Its `mode` means:

| Mode | Badge | Meaning |
|---|---|---|
| `offline` | "Offline agent mode" | The mock provider is selected; AI tasks use rule-based offline answers |
| `offline_unconfigured` | "Offline agent mode" (hover for the reason) | A provider was chosen but is missing settings, e.g. no `LLM_BASE_URL` |
| `live` | the model name, green | A provider is configured and no fallback has been recorded in this server process; this can appear before its first call |
| `degraded` | the model name, amber, "· N fallbacks" | One or more provider calls fell back during this server process; the count remains until restart |

Check the task trace and audit record for the model result used in a particular decision.
Provider failures that use the mock are marked `LLM → fallback` in the activity feed and with
`(fallback)` in the audit record's `model_version`. If fallback is disabled, failures can surface
as errors or failed safety checks; the badge alone does not prove the provider is working.

An ambiguous ingredient that cannot be confirmed remains uncertain and is withheld for review.
Offline fallback keeps supported workflows usable; it cannot turn an unsupported safety claim
into a compliant item.

## Resetting demo data

Seeding an existing database does not update its catalogue or ingredient rules. A reset reloads
the current source's seed data, but **deletes every account, household, preference, basket,
review and audit record in the configured database**. Stop the app and keep a database backup
before resetting any data you need. Check `DATABASE_URL` and env files first: the reset targets
that configured database, not necessarily the default local file.

For a disposable local demo, run from `backend/`:

```bash
.venv/bin/python -m app.seed --reset
```

On Windows, use `.\.venv\Scripts\python.exe -m app.seed --reset` instead.

For a disposable Compose demo, `docker compose down -v` removes the project's database volume.
The `-v` option also requests removal of the declared `ollama-models` volume, so downloaded
models may need to be fetched again. Then run `docker compose up --build`. This does not remove the separate
volume created by the `docker run` examples in `CI_CD.md`.

## Recovery

| Problem | Fix |
|---|---|
| Badge says `degraded`, or a provider times out | Check that provider's connection, key and model; the campus proxy also needs the uni VPN. Uncertain ingredients remain withheld. To run fully offline, set `LLM_PROVIDER=mock` and restart the backend. |
| Badge says `offline_unconfigured` | Hover the badge for the missing setting, fix `.env`, restart the backend |
| Old or inconsistent demo catalogue | Back up needed data, then follow [Resetting demo data](#resetting-demo-data) for a disposable demo |
| Errors after pulling database schema changes | There are no migration scripts. Preserve needed data before replacing or resetting the demo database |
| Everyone is signed out | `backend/.secret_key` was deleted or `SECRET_KEY` changed; sign in again |
| `Can't reach the Trolley Mate server` in the UI | The backend isn't running on port 8000; start it with `scripts/dev.*` |
| Port 8000 or 5173 already in use | Stop your conflicting dev server, or launch the backend from its venv on another port and set `VITE_API_PROXY` in the frontend process environment; Vite reads that variable from the process, not automatically from the root `.env` |
| Frontend build errors about missing modules | `cd frontend && npm ci` (stale `node_modules`) |
| Python install or resolver errors | Check Python 3.12+ and use the project's venv. From `backend/`, reinstall `requirements-dev.txt`; use `python -m pip check` to check the result |
| Docker image won't start | Read `docker compose logs app` first. Check configuration, ports and database compatibility before considering a data reset |
