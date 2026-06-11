<#
  stop_live.ps1 — stop the live WhatsApp stack started by run_live.ps1.
  Kills the cloud server on :8001, the outbox Celery worker, and ngrok.
  Leaves any OTHER uvicorn (e.g. the mock simulator on :8000) untouched.
#>

param([int]$Port = 9001)

# ngrok
Get-Process ngrok -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.Id -Force; Write-Host "stopped ngrok (PID $($_.Id))"
}

# server on $Port
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $conn | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        Write-Host "stopped server on :$Port (PID $($_.OwningProcess))"
    }
} else { Write-Host "no server on :$Port" }

# celery workers
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'celery' } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "stopped celery worker (PID $($_.ProcessId))"
    }

Write-Host "Done." -ForegroundColor Green
