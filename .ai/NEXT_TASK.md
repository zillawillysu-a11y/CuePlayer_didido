# Next task

**Status:** Awaiting user packaging validation
**Type:** Release validation (1.1.3 Windows)
**Updated:** 2026-08-12

## Do this first

1. Run `packaging/build_windows.ps1` from PowerShell.
2. Confirm `dist/CuePlayer-1.1.3-YYYYMMDD-win64.zip` is generated.
3. If Inno Setup is installed, confirm `dist/CuePlayer-Setup-1.1.3.exe` exists.
4. Launch the packaged executable and smoke-test Beat Grid edit, color undo,
   move/resize undo, Mark overlap priority, and playback.

## Relevant files

- `packaging/build_windows.ps1`
- `packaging/CuePlayer.iss`
- `packaging/cueplayer.spec`
- `pyproject.toml`
- `src/cueplayer/__init__.py`
