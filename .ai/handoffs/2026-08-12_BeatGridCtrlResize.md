# Beat Grid Ctrl-resize handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Completed

- Ctrl+drag Start resizes the leading boundary.
- Ctrl+drag End resizes the trailing boundary.
- Normal drag still translates the entire grid.
- Resize operations are recorded by the song undo stack.
- Bounds are clamped to the song and retain at least one subdivision.

## Verification

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
& '.\.venv\Scripts\python.exe' -m pytest -q tests\domain\test_beat_grid.py tests\ui\test_beat_grid_selection.py -x
```

Result: `18 passed`.

## Next step

Validate both endpoints and undo/redo in the Windows application.
