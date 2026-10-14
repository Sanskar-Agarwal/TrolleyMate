# Start backend (port 8000) and frontend (port 5173) in two windows:  .\scripts\dev.ps1
$root = Split-Path -Parent $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"
Write-Host "Backend  http://localhost:8000/docs"
Write-Host "Frontend http://localhost:5173  (demo password for every account: demo1234)"
