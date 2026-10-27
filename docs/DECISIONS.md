# Technology decisions

Short records of the choices behind the prototype, so reviewers and teammates can see why
each one was made and what was given up. Owner: Maaz (KAN-25). Agreed at sprint 1 planning.

## D1 — Framework: FastAPI + React (TypeScript, Vite)

- **Chosen:** FastAPI on Python 3.12 for the API and agents; React 19 + TypeScript built with Vite.
- **Why:** the course's agent material (LangChain/LangGraph labs) is Python, the optimiser
  needs SciPy, and FastAPI gives typed request validation and live OpenAPI docs at `/docs`
  that the frontend team codes against. React is listed in the Stage 2 brief as an
  application framework.
- **Rejected:** Flask (no request validation or schema docs), Next.js (a second server
  runtime for no gain — the backend already serves the built SPA).

## D2 — AI integration: one `LLMService`, many providers, always a fallback

- **Chosen:** every LLM call goes through `backend/app/llm/service.py` as a named *task*
  (prompt + JSON schema + offline mock). Providers: `mock`, `openai_compatible` (ELEC5620
  Campus Qwen proxy, OpenAI, Ollama), `anthropic`.
- **Why:** teammates hold different keys, the campus proxy needs the uni VPN, and the demo
  must run on a machine we don't control. If the provider fails, the task's mock answers
  and the result is flagged `fell_back` in the UI badge, the activity feed and the audit log.
- **Boundary (Stage 1 §4.1):** the LLM interprets, routes, explains and judges vague
  ingredients. It never prices, solves or declares an item safe — those stay deterministic.
- **Rejected:** LangChain agents end to end (harder to make deterministic for tests and to
  audit per decision); a single hard-wired provider (demo fails without the VPN).

## D3 — Persistence: SQLAlchemy 2 on SQLite, Postgres-ready

- **Chosen:** SQLite file in `backend/` (or `/data` in Docker), created and seeded on start.
- **Why:** zero setup for the on-site demo; `DATABASE_URL` switches to Postgres unchanged.
- **Trade-off:** no migrations — schema changes mean `python -m app.seed --reset`.

## D4 — Deployment: one container, plus a no-Docker path

- **Chosen:** a multi-stage Dockerfile builds the React app and serves it from FastAPI on
  port 8000 (`docker compose up --build`). `scripts/setup.*` + `scripts/dev.*` run the same
  app without Docker. CI builds, smoke-tests and publishes the image (see `CI_CD.md`).
- **Why:** the Week 13 demo downloads the source from Canvas and deploys on site; one
  command and no external services is the safest path.

## D5 — Auth: signed bearer tokens with three roles

- **Chosen:** PBKDF2 password hashes and HMAC-signed tokens carrying `shopper`,
  `dietitian` or `founder`. The signing key is generated per install when unset.
- **Why:** enough to demonstrate role separation (shopper vs authorised reviewer vs
  founder audit) without an external identity provider. See `API_CONTRACTS.md` for the
  permission matrix.
