<#
  run_live.ps1 — bring up the WhatsApp Cloud API live stack in ONE command.

  Starts (each in its own window so you can watch logs):
    1. Celery worker  (delivers bot replies)        queues: outbox,celery
    2. FastAPI server (cloud mode)                  http://localhost:8001
    3. ngrok tunnel   (STATIC domain -> port 8001)  stable public callback URL

  Credentials (token, phone-number-id, app-secret, verify-token) are read from
  .env automatically by the app — nothing is hardcoded here.

  PREREQUISITES (one-time):
    * docker compose up -d            (postgres + redis must be running)
    * Claim a free static ngrok domain at https://dashboard.ngrok.com/domains
      and put it in $NgrokDomain below (or pass -NgrokDomain ...).
    * In .env set APP_WHATSAPP_PROVIDER=cloud and the APP_WA_* values.
    * In Meta -> WhatsApp -> Configuration, set the webhook ONCE to:
        https://<your-static-domain>/webhooks/whatsapp
      verify token = your APP_WA_VERIFY_TOKEN, and Subscribe to "messages".

  USAGE:
    powershell -ExecutionPolicy Bypass -File scripts\run_live.ps1
    powershell -ExecutionPolicy Bypass -File scripts\run_live.ps1 -NgrokDomain my-name.ngrok-free.app
#>

param(
    # Your account's permanent free static ngrok domain (auto-assigned by ngrok).
    # Callback URL stays the same every run: https://<this>/webhooks/whatsapp
    [string]$NgrokDomain = "yelena-manatoid-teressa.ngrok-free.dev",
    # 9001, not 8001: Windows/Hyper-V reserves the 7949-8048 range after Docker
    # restarts (bind fails with winerror 10013). 9001 sits outside it.
    [int]$Port = 9001,
    [string]$NgrokExe = "$env:USERPROFILE\Downloads\ngrok.exe"
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Repo ".venv\Scripts\python.exe"

if ($NgrokDomain -eq "CHANGE-ME.ngrok-free.app") {
    Write-Host "ERROR: Set your static ngrok domain first." -ForegroundColor Red
    Write-Host "  1. Claim one (free) at https://dashboard.ngrok.com/domains"
    Write-Host "  2. Edit `$NgrokDomain at the top of this script, or pass -NgrokDomain <domain>"
    exit 1
}
if (-not (Test-Path $Py)) { Write-Host "ERROR: venv python not found at $Py" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $NgrokExe)) { Write-Host "ERROR: ngrok.exe not found at $NgrokExe" -ForegroundColor Red; exit 1 }

Write-Host "Repo:    $Repo"
Write-Host "Python:  $Py"
Write-Host "Tunnel:  https://$NgrokDomain  ->  http://localhost:$Port"
Write-Host ""

# 1) Celery worker (own window). PYTHONPATH=src so `app` imports; cwd=repo so `apps` imports.
Start-Process powershell -ArgumentList @(
    "-NoExit","-Command",
    "Set-Location '$Repo'; `$env:PYTHONPATH='src'; & '$Py' -m celery -A apps.workers.celery_app:celery_app worker --pool=solo -Q outbox,celery --loglevel=info"
)
Write-Host "[1/3] Celery worker starting..." -ForegroundColor Green

# 2) FastAPI server (own window).
Start-Process powershell -ArgumentList @(
    "-NoExit","-Command",
    "Set-Location '$Repo'; & '$Py' -m uvicorn app.main:app --app-dir src --port $Port"
)
Write-Host "[2/3] FastAPI server starting on :$Port..." -ForegroundColor Green

Start-Sleep -Seconds 3

# 3) ngrok with the STATIC domain (own window). Stable callback URL every run.
Start-Process powershell -ArgumentList @(
    "-NoExit","-Command",
    "& '$NgrokExe' http $Port --url https://$NgrokDomain"
)
Write-Host "[3/3] ngrok tunnel starting (static domain)..." -ForegroundColor Green

Write-Host ""
Write-Host "Live. Callback URL (configure in Meta ONCE):" -ForegroundColor Cyan
Write-Host "    https://$NgrokDomain/webhooks/whatsapp" -ForegroundColor Cyan
Write-Host "To stop everything:  scripts\stop_live.ps1" -ForegroundColor Yellow
