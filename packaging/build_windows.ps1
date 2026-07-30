#Requires -Version 5.1
<#
.SYNOPSIS
  Build a Windows CuePlayer folder (+ optional Setup.exe) for employee installs.

.DESCRIPTION
  Run this on a Windows machine with the same Python you use for CuePlayer.
  Cloud / Linux agents cannot produce a usable Windows audio/video build.

  Output:
    dist\CuePlayer\CuePlayer.exe     - portable folder (zip this for quick share)
    dist\CuePlayer-Setup-*.exe       - Inno Setup 7/6 installer (if ISCC is installed)

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipZip,
    [switch]$SkipInno,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Find-Python {
    param([string]$Preferred)
    if ($Preferred -and (Test-Path $Preferred)) { return $Preferred }
    $venv = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $venv) { return $venv }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "Python not found. Create .venv or pass -Python path."
}

$Py = Find-Python -Preferred $Python
Write-Host "Using Python: $Py"
& $Py -c "import sys; print(sys.version); assert sys.platform == 'win32', 'Build CuePlayer Windows packages on Windows only'"
if ($LASTEXITCODE -ne 0) {
    throw "Python check failed (need Windows + Python)."
}

Write-Host "Installing / refreshing runtime + PyInstaller..."
& $Py -m pip install -U pip setuptools wheel
# Single-quote extras so PowerShell does not parse [dev,midi,ndi] as an expression.
# ndi (cyndilib) is required in the employee build so NDI OUTPUT works from CuePlayer.exe.
& $Py -m pip install -e '.[dev,midi,ndi]'
& $Py -c "import cyndilib; print('cyndilib OK', getattr(cyndilib, '__version__', '?'))"
if ($LASTEXITCODE -ne 0) {
    throw "cyndilib import failed. Install NDI extra failed - cannot ship NDI OUTPUT."
}
& $Py -m pip install -U 'pyinstaller>=6.3'

$Spec = Join-Path $Root "packaging\cueplayer.spec"
$Dist = Join-Path $Root "dist"
$Build = Join-Path $Root "build"

if (Test-Path $Dist) { Remove-Item -Recurse -Force $Dist }
if (Test-Path $Build) { Remove-Item -Recurse -Force $Build }

Write-Host "Running PyInstaller (onedir)..."
& $Py -m PyInstaller --noconfirm --clean $Spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed (exit $LASTEXITCODE)"
}

$AppDir = Join-Path $Dist "CuePlayer"
$Exe = Join-Path $AppDir "CuePlayer.exe"
if (-not (Test-Path $Exe)) {
    throw "Build failed: missing $Exe"
}
Write-Host "OK: $Exe"

$Version = (& $Py -c "from cueplayer import __version__; print(__version__)").Trim()
$Stamp = Get-Date -Format "yyyyMMdd"
$ArtifactBase = "CuePlayer-$Version-$Stamp-win64"

if (-not $SkipZip) {
    $Zip = Join-Path $Dist "$ArtifactBase.zip"
    if (Test-Path $Zip) { Remove-Item -Force $Zip }
    Write-Host "Zipping portable folder -> $Zip"
    Compress-Archive -Path $AppDir -DestinationPath $Zip -CompressionLevel Optimal
    Write-Host "OK: $Zip"
}

if (-not $SkipInno) {
    # Prefer Inno Setup 7 (e.g. 7.0.2), fall back to 6. Build machine only.
    $Iscc = $null
    $pf = ${env:ProgramFiles}
    $pf86 = ${env:ProgramFiles(x86)}
    $local = $env:LocalAppData
    foreach ($candidate in @(
            (Join-Path $pf "Inno Setup 7\ISCC.exe"),
            (Join-Path $pf86 "Inno Setup 7\ISCC.exe"),
            (Join-Path $local "Programs\Inno Setup 7\ISCC.exe"),
            (Join-Path $pf "Inno Setup 6\ISCC.exe"),
            (Join-Path $pf86 "Inno Setup 6\ISCC.exe"),
            (Join-Path $local "Programs\Inno Setup 6\ISCC.exe")
        )) {
        if ($candidate -and (Test-Path $candidate)) {
            $Iscc = $candidate
            break
        }
    }
    if ($null -eq $Iscc) {
        Write-Host "Inno Setup not found - skipping Setup.exe (zip is enough for internal test)."
        Write-Host "Optional: install Inno Setup 7 from https://jrsoftware.org/isdl.php then re-run."
    }
    else {
        $Iss = Join-Path $Root "packaging\CuePlayer.iss"
        Write-Host "Building installer with $Iscc ..."
        & $Iscc "/DMyAppVersion=$Version" $Iss
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup compile failed (exit $LASTEXITCODE)"
        }
        $Setup = Get-ChildItem $Dist -Filter "CuePlayer-Setup-*.exe" |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($Setup) {
            Write-Host "OK: $($Setup.FullName)"
        }
    }
}

Write-Host ""
Write-Host "=== Share with employees ==="
Write-Host "Quick:   send dist\$ArtifactBase.zip  then unzip and run CuePlayer.exe"
Write-Host "Install: send dist\CuePlayer-Setup-$Version.exe (if built)"
Write-Host ""
