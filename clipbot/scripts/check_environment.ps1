<#
.SYNOPSIS
  Checks Python, FFmpeg, Ollama, the configured model, RAM, NVIDIA GPU and disk space.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\check_environment.ps1
#>
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Show($status, $name, $detail) {
    $color = @{ OK = "Green"; WARN = "Yellow"; FAIL = "Red" }[$status]
    Write-Host ("[{0,-4}] {1}: {2}" -f $status, $name, $detail) -ForegroundColor $color
}

Write-Host "Windows-level checks" -ForegroundColor Cyan
$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
Show "OK" "Windows" "$($os.Caption) $($os.Version)"
$ramGB = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
$freeGB = [math]::Round($os.FreePhysicalMemory * 1KB / 1GB, 1)
Show ($(if ($ramGB -ge 16) { "OK" } else { "WARN" })) "RAM" "$ramGB GB total, $freeGB GB free"
$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1)
Show "OK" "CPU" "$($cpu.Name.Trim()) - $($cpu.NumberOfCores) cores / $($cpu.NumberOfLogicalProcessors) threads"

$gpus = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match "NVIDIA" }
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) {
    $q = & nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>$null
    if ($LASTEXITCODE -eq 0 -and $q) { Show "OK" "NVIDIA GPU" "$q (driver installed - Ollama decides if it can use it)" }
    else { Show "WARN" "NVIDIA GPU" "nvidia-smi present but returned no GPU" }
} elseif ($gpus) {
    Show "WARN" "NVIDIA GPU" "$($gpus.Name -join ', ') found but nvidia-smi is missing - install the NVIDIA driver for GPU use; CPU works without it"
} else {
    Show "WARN" "NVIDIA GPU" "none detected - CPU inference will be used"
}

$drive = (Get-Item $Root).PSDrive
$diskGB = [math]::Round($drive.Free / 1GB, 1)
Show ($(if ($diskGB -ge 15) { "OK" } else { "WARN" })) "Disk" "$diskGB GB free on $($drive.Name):"

foreach ($t in @("ffmpeg", "ffprobe", "ollama")) {
    $c = Get-Command $t -ErrorAction SilentlyContinue
    if ($c) { Show "OK" "$t on PATH" $c.Source } else { Show $(if ($t -eq "ollama") { "WARN" } else { "FAIL" }) "$t on PATH" "not found" }
}

Write-Host "`nClipBot checks (python -m clipbot.check_env)" -ForegroundColor Cyan
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Show "FAIL" "Python venv" ".venv not found - run scripts\setup_windows.ps1 first"
    exit 1
}
& $venvPy -m clipbot.check_env
exit $LASTEXITCODE
