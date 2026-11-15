<#
.SYNOPSIS
  One-time ClipBot setup on Windows 10/11 (no Docker needed).
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
  powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -InstallTools -DownloadSpeechModels -PullModel
.NOTES
  -InstallTools          installs Python 3.13, FFmpeg (Gyan full build, includes libass + libx264) and Ollama with winget
  -DownloadSpeechModels  downloads Kokoro (~90 MB) + Whisper (~150 MB) into data\models
  -PullModel             downloads OLLAMA_MODEL from .env through Ollama (qwen3:4b is ~2.5 GB)
  Nothing is downloaded unless you pass these switches.
#>
param(
    [switch]$InstallTools,
    [switch]$DownloadSpeechModels,
    [switch]$PullModel
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

if ($InstallTools) {
    Step "Installing tools with winget"
    foreach ($id in @("Python.Python.3.13", "Gyan.FFmpeg", "Ollama.Ollama")) {
        winget install --id $id -e --accept-source-agreements --accept-package-agreements
    }
    # make newly installed tools visible in this session
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

Step "Finding Python 3.11+"
$candidates = @(
    @{ Exe = "py"; Args = @("-3.13") },
    @{ Exe = "py"; Args = @("-3.12") },
    @{ Exe = "py"; Args = @("-3.11") },
    @{ Exe = "python"; Args = @() }
)
$py = $null
foreach ($c in $candidates) {
    if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
    $pyArgs = $c.Args
    $v = & $c.Exe @pyArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -eq 0 -and $v -and [version]$v -ge [version]"3.11") { $py = $c; break }
}
if (-not $py) { throw "Python 3.11+ not found. Install it (winget install Python.Python.3.13) or rerun with -InstallTools." }
Write-Host "Using: $($py.Exe) $($py.Args -join ' ') (Python $v)"

Step "Creating virtual environment .venv"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $pyArgs = $py.Args + @("-m", "venv", ".venv")
    & $py.Exe @pyArgs
    if ($LASTEXITCODE -ne 0) { throw "could not create .venv" }
}
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r requirements.txt -c requirements.lock
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Step "Configuration"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example - edit it (notepad .env) before starting."
} else { Write-Host ".env already exists - left unchanged." }

if ($DownloadSpeechModels) {
    Step "Downloading speech models (Kokoro + Whisper)"
    & $venvPy scripts\download_models.py --speech
    if ($LASTEXITCODE -ne 0) { throw "speech model download failed" }
}

if ($PullModel) {
    Step "Pulling the Ollama model from .env"
    & $venvPy scripts\download_models.py --ollama
    if ($LASTEXITCODE -ne 0) { throw "Ollama pull failed - is Ollama running? (start the Ollama app)" }
}

Step "Environment check"
& (Join-Path $PSScriptRoot "check_environment.ps1")
