# One-time setup on Windows (PowerShell):  .\scripts\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "==> Backend: creating virtualenv and installing packages"
Push-Location "$root\backend"
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip -q
& .\.venv\Scripts\pip.exe install -r requirements-dev.txt -q
& .\.venv\Scripts\python.exe -m app.seed
Pop-Location

Write-Host "==> Frontend: installing packages"
Push-Location "$root\frontend"
npm install --no-audit --no-fund
Pop-Location

if (-not (Test-Path "$root\.env")) {
  Copy-Item "$root\.env.example" "$root\.env"
  Write-Host "==> Created .env from .env.example (runs offline on the mock LLM until you add a key)"
}
Write-Host "Done. Start everything with: .\scripts\dev.ps1"
