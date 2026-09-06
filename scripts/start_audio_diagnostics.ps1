# Start this checkout with the existing Tools -> Write Performance Report menu.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Project .venv is missing. Install the development environment first.'
}
$logDir = Join-Path $projectRoot '.cache/audio-diagnostics'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$env:CUEPLAYER_AUDIO_TRACE = '1'
$env:CUEPLAYER_PERF = '1'
$env:CUEPLAYER_PERF_LOG = Join-Path $logDir "audio-perf-$stamp.txt"
Write-Output "Performance log: $env:CUEPLAYER_PERF_LOG"
Start-Process -FilePath $pythonPath -ArgumentList @('-m', 'cueplayer') `
    -WorkingDirectory $projectRoot -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir "stdout-$stamp.txt") `
    -RedirectStandardError (Join-Path $logDir "stderr-$stamp.txt") -PassThru |
    Select-Object Id,ProcessName
