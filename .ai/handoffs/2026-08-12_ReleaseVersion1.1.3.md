# CuePlayer 1.1.3 release version handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Completed

- `pyproject.toml`: 1.1.3
- `cueplayer.__version__`: 1.1.3
- Inno Setup fallback/default: 1.1.3
- Runtime version assertion passed.

## Packaging entry point

```powershell
Set-Location 'C:\Users\User\Projects\CuePlayer_v2'
powershell -ExecutionPolicy Bypass -File '.\packaging\build_windows.ps1'
```

## Expected output

- `dist/CuePlayer-1.1.3-YYYYMMDD-win64.zip`
- `dist/CuePlayer-Setup-1.1.3.exe` when Inno Setup is installed

## Next step

Build and smoke-test the packaged Windows application before distribution.
