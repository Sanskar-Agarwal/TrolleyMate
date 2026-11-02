# OpenTelemetry tracing and Jaeger

The optional observability stack shows where a request spends time across the API,
agent, language-model call and basket optimiser. It also distinguishes a failed model
call from a successful offline fallback. This is operational monitoring alongside the
application's user-facing audit records.

## Start the complete demo

With Docker running and `.env` configured as described in the README:

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up --build
```

Open the app at http://localhost:8000 and Jaeger at http://localhost:16686.
Use the application normally, then select service **trolleymate** in Jaeger and click
**Find Traces**. Open a `POST /sessions/{session_id}/basket` trace to inspect its timing waterfall.

For an existing native backend, start only the collector:

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d jaeger
```

Set the following in `.env`, then restart the backend:

```dotenv
TRACING_ENABLED=true
TRACING_ENDPOINT=http://127.0.0.1:4318/v1/traces
TRACING_SAMPLE_RATIO=1.0
```

Normal startup defaults to tracing disabled and does not require Jaeger. The Compose
observability override enables it and uses the collector's internal Docker hostname.

## Presentation demonstration

1. Log in as a demo shopper and submit a grocery request.
2. Confirm the interpreted requirements and generate a basket.
3. In Jaeger, find the request and expand its spans: `agent.think`, `ai.task`,
   `ai.provider.call` (live mode), `basket.build` and `basket.optimise`, where applicable.
4. Explain the durations, parent–child relationships and any error/fallback indicators.
   Each API response carries an `X-Trace-ID` for correlation when tracing is enabled.

This demonstrates **OpenTelemetry instrumentation and Jaeger observability** as a
separate technology from React, CI/CD, Docker packaging and application security.
The current spans follow work within this backend; they do not instrument Groq's
internal infrastructure.

## Data and reliability

- Attributes contain route templates, HTTP status, agent/task/model identifiers,
  fallback flags and exception class names. Prompts, dietary details, passwords,
  tokens, raw URLs/query strings and exception messages are not added to traces.
- Export runs in a bounded background queue. An unavailable collector can lose traces
  but does not prevent the application from serving requests.
- Sampling is configurable between 0 and 1; the local demo records all traces by default.
- Jaeger uses temporary in-memory storage in this demo. Restarting the container clears
  traces. Its unauthenticated UI and ingestion port are bound to localhost only.
- These operational traces supplement, and do not replace, persistent decision audits.

References: [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/instrumentation/)
and [Jaeger getting started](https://www.jaegertracing.io/docs/2.22/getting-started/).

## Verification — 31 October 2026

- Backend regression suite passed (535 tests at the time of the full run).
- All six observability tests passed, including the subsequently added collector-failure test.
- Ruff checks and the Docker application build passed, including locked dependency validation.
- Browser UAT used the live Groq provider: sign-in, request interpretation, confirmation
  and basket generation succeeded. Jaeger displayed the six-span basket waterfall with
  `ai.fallback=false`, linked request/agent/model/optimiser timings and HTTP 200.
- [Dashboard evidence](evidence/2026-10-31-observability/trace-waterfall.png).
