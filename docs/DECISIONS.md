# Technology decisions

Short records of the choices behind the prototype, so reviewers and teammates can see why
each one was made and what was given up. Owner: Maaz (KAN-25). Agreed at sprint 1 planning.

Implementation notes checked against the source on 2026-10-29. The original decision
rationale is retained; the boundaries below describe the current prototype.

## D1 — Framework: FastAPI + React (TypeScript, Vite)

- **Chosen:** FastAPI on Python 3.12 for the API and agents; React 19 + TypeScript built with Vite.
- **Why:** the course's agent material (LangChain/LangGraph labs) is Python, the optimiser
  needs SciPy, and FastAPI gives typed request validation and live OpenAPI docs at `/docs`
  that the frontend team codes against. React is listed in the Stage 2 brief as an
  application framework.
- **Rejected:** Flask (no built-in request validation or schema docs), Next.js (a second server
  runtime for no gain — the backend already serves the built SPA).

## D2 — AI integration: one `LLMService`, many providers, configurable fallback

- **Chosen:** every LLM call goes through `backend/app/llm/service.py` as a named *task*
  (prompt + JSON schema + offline mock). Providers: `mock`, `openai_compatible` (ELEC5620
  Campus Qwen proxy, OpenAI, Ollama), `anthropic`.
- **Why:** teammates hold different keys, the campus proxy needs the uni VPN, and the demo
  must run on a machine we don't control. `LLM_PROVIDER=mock` is the default offline mode.
  For a configured provider, failed calls or invalid responses fall back to the task's mock
  with `fell_back=true` when `LLM_FALLBACK_TO_MOCK=true` (the default); setting it to `false`
  propagates those errors instead.
- **Configuration limit:** provider construction errors currently leave the service in
  `offline_unconfigured`, where tasks use mocks even if fallback is disabled. A live-provider
  check must inspect the reported mode as well as the fallback setting.
- **Boundary (Stage 1 §4.1):** the LLM interprets, routes, explains and judges vague
  ingredients; pricing and optimisation are implemented separately. Ingredient screening
  combines recursive tag checks, missing-data checks, applicable dietitian decisions and
  model judgements. For ambiguous ingredients, a `none` risk judgement at or above the
  confidence threshold can contribute to a `compliant` result. Failed assessments and
  low-confidence or possible-risk results remain uncertain; a fallback judgement cannot
  clear an ingredient as risk-free. Intentional mock mode uses its own rules and guidance.
  These are prototype screening outcomes, not a clinical guarantee of safety (see
  `backend/app/agents/nutrition_compliance.py`).
- **Rejected:** LangChain agents end to end (harder to make deterministic for tests and to
  audit per decision); a single hard-wired provider (demo fails without the VPN).

## D3 — Persistence: SQLAlchemy 2 on SQLite

- **Chosen:** SQLite file in `backend/` (or `/data` in Docker). Startup creates missing
  tables with `create_all()`; with `SEED_ON_STARTUP=true` it seeds only when no user row
  exists. Editing the seed JSON does not update an existing seeded database.
- **Why:** zero database-server setup for the on-site demo. `DATABASE_URL` is configurable,
  but PostgreSQL also requires a separately installed driver and a provisioned database;
  the bundled dependencies do not include `psycopg`. PostgreSQL compatibility is not
  established merely by changing the URL.
- **Trade-off:** there is no migration framework, and `create_all()` does not migrate
  existing tables. `python -m app.seed --reset` drops and recreates application tables,
  including user and session data; use it only for a disposable demo database. Retaining
  existing data across schema changes requires a reviewed migration approach.

## D4 — Deployment: one container, plus a no-Docker path

- **Chosen:** a multi-stage Dockerfile builds the React app and serves it from FastAPI on
  port 8000 (`docker compose up --build`). `scripts/setup.*` + `scripts/dev.*` run the same
  app without Docker. CI builds and smoke-tests the image; successful pushes to `main`
  publish that tested image to GHCR (see [CI/CD](CI_CD.md)). Publishing an image does not
  deploy a hosted instance.
- **Why:** the Week 13 demo downloads the source from Canvas and deploys on site; one
  command and mock mode allow the demo to run without external AI or retailer services.
- **Persistence boundary:** Compose mounts the SQLite database at `/data` in a named
  volume. The default image runs one Uvicorn process; deployment assumptions such as
  process-local workflow state must be reconsidered before adding workers or replicas.

## D5 — Auth: revocable bearer sessions with three roles

- **Chosen (updated 30 October 2026):** salted PBKDF2-HMAC-SHA256 password hashes
  at 600,000 iterations and opaque random bearer tokens. Only token digests are stored;
  roles (`shopper`, `dietitian`, `founder`) are read from the user record. Old signed
  tokens are retired and existing password hashes upgrade on successful login.
- **Limits:** three concurrent logins, 30-minute idle expiry and eight-hour absolute expiry.
  Server-side sign-out revokes one or all sessions. CSRF checks and database-backed
  request limits protect API writes and authentication. See [security](SECURITY.md).
- **Persistence:** login sessions live in the application database. Rate counters use an
  adjacent SQLite `.limits` file so long basket writes do not block counter updates.
  `SECRET_KEY` now keys hashed rate-limit identities; use one stable key across workers.
- **Why:** demonstrate role separation and revocable access without an external identity
  provider. See [API contracts](API_CONTRACTS.md) for the permission matrix.
