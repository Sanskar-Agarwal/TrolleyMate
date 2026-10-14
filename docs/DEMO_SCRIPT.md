# Week 13 demo script (≈ 8 minutes)

Run from the Canvas zip on the demo machine:

```bash
docker compose up --build          # → http://localhost:8000
```

or without Docker: `scripts/setup.ps1` then `scripts/dev.ps1` (→ http://localhost:5173).
Reset data before presenting: `cd backend && .venv/Scripts/python -m app.seed --reset`.
If the campus VPN / LLM is unavailable, the app keeps working on the offline agent mode — say so.

| # | Do | Say (criterion) |
|---|---|---|
| 1 | Sign in as **Alex** (household: Alex lactose-intolerant, Jamie tree-nut allergy). Open **Household** briefly. | UC-10: profiles drive every shop. Mandatory restrictions vs soft preferences. (C1) |
| 2 | **Shop** → type *"I have $100 for this week, two meals a day for us two. High protein please."* | Perception: the LLM extracts budget/days/meals, merges household allergies, and **asks** about "high protein" instead of assuming. Point at the activity feed. (C2) |
| 3 | Answer *"120g"*, change one field to show a correction, then **Confirm**. | UC-01 state machine: clarifications ≠ corrections; third correction switches to a form. (C1) |
| 4 | Pick **Balanced** → **Build my basket**. | The primary workflow: Market Analyst prices 3 retailers (refreshes stale quotes), Compliance screens (milk/almond/pesto excluded — expand "left out for safety"), MILP solver optimises, Compliance verifies. (C1, C4: optimisation solver) |
| 5 | Show the **schnitzel held for a dietitian**. | Human approval gate: incomplete ingredient data → confidence 40% < 95% threshold → escalated, withheld from the total. (C2) |
| 6 | Click **Why this basket?** and **Why this?** on an item. | UC-07: explanations generated only from recorded facts. (C2) |
| 7 | Sign out → **Dr Sam Patel** → open the case → *Request info* → **Safe — release**. | UC-06 extension, State machine 9.5; the compliance agent answers the dietitian. Do this **before** editing the basket, so the released item is still in it. |
| 8 | Sign in as **Alex** again: item released, basket now "Safe-checked" and can be accepted. | The human decision is applied and remembered for this household. |
| 9 | Chat *"Replace the lentils with chicken"*. | UC-09: LLM turns language into solver pins; mandatory rules stay. (C2) |
| 10 | **Find a substitute** on an item → accept. | UC-04 trade-off sentence; declined swaps never re-offered. |
| 11 | **Compare stores** tab, switch baseline. **When to buy** tab. | UC-05 split basket savings; 1.2.6 recurring-discount detection (e.g. cheddar on Tuesdays, turkey mince on Wednesdays). |
| 12 | **Meal plan** tab → Plan my meals. | UC-08: recipes only from the basket, shared packs, gaps reported not silently filled. |
| 13 | **Start a new shop**: *"$30 for the week, three meals a day for two of us"* → confirm → build. | UC-03: infeasible → minimum extra budget **or** max days; pick one → rebuilt. |
| 14 | Sign in as **Maya (founder)** → **Agent audit**: filter by agent, open a trace to show the raw prompt/response and model version. | Governance outside the supervisor chain; per-decision model attribution. (C2, C4) |
| 15 | Show GitHub PRs + CI runs, Jira board/burndown, sprint tags. | Agile: iterations, reviews, feedback loops. (C3) |

**Advanced technologies to name (C4):** React + TypeScript SPA; FastAPI; multi-agent supervisor–worker
with LLM tool-style tasks; pluggable LLMs (Campus Qwen / local Ollama model / Claude) with automatic
fallback; integer-linear-programming optimiser (SciPy/HiGHS); Docker single-container deploy; GitHub
Actions CI with a container smoke test.
