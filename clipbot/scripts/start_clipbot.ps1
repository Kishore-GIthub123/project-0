<#
.SYNOPSIS
  Starts the ClipBot worker and dashboard (no Docker). Ctrl+C stops both.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\start_clipbot.ps1
  powershell -ExecutionPolicy Bypass -File scripts\start_clipbot.ps1 -Port 8080 -SkipCheck
#>
param(
    [int]$Port = 8000,
    [switch]$SkipCheck,
    [switch]$DashboardOnly
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { throw ".venv not found - run scripts\setup_windows.ps1 first" }
if (-not (Test-Path ".env")) { throw ".env not found - copy .env.example to .env and edit it" }

if (-not $SkipCheck) {
    & $venvPy -m clipbot.check_env
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Environment check reported FAIL items (see above). Fix them or rerun with -SkipCheck." -ForegroundColor Yellow
        exit 1
    }
}

$logs = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$procs = @()
try {
    $procs += Start-Process -FilePath $venvPy -WorkingDirectory $Root -PassThru -NoNewWindow `
        -ArgumentList @("-m", "uvicorn", "clipbot.dashboard:app", "--host", "127.0.0.1", "--port", "$Port") `
        -RedirectStandardOutput (Join-Path $logs "dashboard.out.log") -RedirectStandardError (Join-Path $logs "dashboard.log")
    Write-Host "Dashboard: http://127.0.0.1:$Port  (user/password from .env)" -ForegroundColor Green
    if (-not $DashboardOnly) {
        $procs += Start-Process -FilePath $venvPy -WorkingDirectory $Root -PassThru -NoNewWindow `
            -ArgumentList @("-m", "clipbot.worker") `
            -RedirectStandardOutput (Join-Path $logs "worker.out.log") -RedirectStandardError (Join-Path $logs "worker.log")
        Write-Host "Worker started. Logs: $logs\worker.log" -ForegroundColor Green
    }
    Write-Host "Press Ctrl+C to stop."
    while ($true) {
        foreach ($p in $procs) {
            if ($p.HasExited) { throw "process $($p.Id) exited with code $($p.ExitCode) - see $logs" }
        }
        Start-Sleep -Seconds 2
    }
} finally {
    foreach ($p in $procs) { if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force } }
    Write-Host "ClipBot stopped."
}
