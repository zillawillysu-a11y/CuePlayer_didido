# BPM Grid Lock handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Allow individual Beat Grids to be protected from accidental dragging.

## What was implemented

- Added checked `BPM Grid Lock` actions to both relevant context-menu paths.
- Locked grids can be selected and used normally except for drag mutations.
- Whole-grid dragging and Ctrl endpoint resizing are blocked.
- Lock persists and supports Ctrl+Z/Ctrl+Y.

## Files changed

- Domain model/snapshot, project persistence, timeline interaction, main-window
  command handling, and Beat Grid tests.

## Architecture decisions

- Lock is a persisted per-grid property; mutation gating stays in Timeline UI.

## Tests performed

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
& '.\.venv\Scripts\python.exe' -m pytest -q tests\domain\test_beat_grid.py tests\ui\test_beat_grid_selection.py -x
```

Result: `20 passed`.

## Remaining issues

- Windows interaction smoke test remains.

## Suggested next task

Validate lock/select/context actions, then rebuild CuePlayer 1.1.3.
