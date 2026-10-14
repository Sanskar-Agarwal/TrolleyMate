#!/usr/bin/env bash
# Start backend (8000) and frontend (5173); Ctrl+C stops both.  ./scripts/dev.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$root/backend" && .venv/bin/python -m uvicorn app.main:app --reload --port 8000) &
backend=$!
trap 'kill $backend 2>/dev/null' EXIT
echo "Backend  http://localhost:8000/docs"
echo "Frontend http://localhost:5173  (demo password for every account: demo1234)"
cd "$root/frontend" && npm run dev
