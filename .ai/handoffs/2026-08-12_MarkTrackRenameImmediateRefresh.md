# Mark Track Rename immediate refresh handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Fix the stale Mark Track header after inline Rename.

## What was implemented

- Rename now bumps the Mark backdrop revision and invalidates the scrub backdrop.
- The main window invokes the canonical Mark UI refresh after the rename signal.
- The updated name no longer depends on a later `set_song()` caused by switching
  songs.

## Files changed

- `src/cueplayer/ui/timeline_widget.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_mark_lane_rename.py`

## Architecture decisions

- Retained rendering remains enabled; only the affected cache is invalidated.
- No song reload or playback changes were introduced.

## Tests performed

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
& '.\.venv\Scripts\python.exe' -m pytest -q tests\ui\test_mark_lane_rename.py tests\ui\test_cached_timeline_poster.py -x
```

Result: `10 passed`.

## Remaining issues

- Windows visual smoke test remains.

## Suggested next task

Validate the immediate Rename refresh, then rebuild CuePlayer 1.1.3.
