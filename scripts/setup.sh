#!/usr/bin/env bash
# One-time setup on macOS / Linux:  ./scripts/setup.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Backend: creating virtualenv and installing packages"
cd "$root/backend"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements-dev.txt -q
.venv/bin/python -m app.seed

echo "==> Frontend: installing packages"
cd "$root/frontend"
npm install --no-audit --no-fund

if [ ! -f "$root/.env" ]; then
  cp "$root/.env.example" "$root/.env"
  echo "==> Created .env from .env.example (runs offline on the mock LLM until you add a key)"
fi
echo "Done. Start everything with: ./scripts/dev.sh"
