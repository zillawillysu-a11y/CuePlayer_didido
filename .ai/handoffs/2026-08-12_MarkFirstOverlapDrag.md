# Mark-first overlap drag handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Objective

Always move a Mark first when it overlaps a Beat Grid line.

## Completed

- Exact Mark/Grid overlap always starts a Mark interaction in Setup mode.
- This is independent of the magnet toggle.
- Magnet remains responsible only for Beat Grid snapping.
- An uncovered division still starts Beat Grid region dragging.

## Verification

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
& '.\.venv\Scripts\python.exe' -m pytest -q tests\ui\test_beat_grid_selection.py -x
```

Result: `11 passed`.

## Next step

Confirm the interaction in the Windows app, including Beat Grid Ctrl+Z/Ctrl+Y.
