# Beat Grid move undo and overlap drag handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Objective

Support Ctrl+Z/Ctrl+Y after moving a Beat Grid and make overlapping Mark/Grid
dragging predictable.

## Completed

- Added `MoveBeatGridCommand` to the song undo stack.
- A completed grid drag records its old and new start once on mouse release.
- Undo/redo moves the whole grid without changing its duration.
- In Setup mode at an exact overlap:
  - magnet on: Mark drag wins;
  - magnet off: Beat Grid drag wins.
- Right-click overlap behavior is unchanged and continues to offer Beat Grid
  actions alongside Mark actions.

## Verification

`15 passed`:

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
& '.\.venv\Scripts\python.exe' -m pytest -q tests\domain\test_beat_grid.py tests\ui\test_beat_grid_selection.py -x
```

## Constraints preserved

- No playback clock, MA exporter, or persistence schema changes.
- Beat Grid UI changes remain in the timeline layer; history logic remains in
  the domain undo layer.

## Next step

Perform hands-on Windows UI validation of grid undo/redo and both magnet overlap
modes, then resume the pending MA3 real-hardware validation.
