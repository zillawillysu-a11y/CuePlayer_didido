# Latest AI task report

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Make Mark dragging always take priority when a Mark overlaps a Beat Grid line.

## What was implemented

- Removed the magnet toggle from overlap hit-test priority.
- In Setup mode, an overlapping Mark now always begins a Mark drag.
- Beat Grid regions remain draggable from any uncovered grid division.
- The magnet toggle now affects snapping only.

## Files changed

- `src/cueplayer/ui/timeline_widget.py`
- `tests/ui/test_beat_grid_selection.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-12_MarkFirstOverlapDrag.md`
- `.ai/NEXT_TASK.md`

## Architecture decisions

- Kept priority resolution in timeline hit-testing; no domain or persistence
  behavior changed.
- Mark-first behavior is unconditional at an exact overlap, giving the most
  commonly edited object a stable interaction rule.

## Tests performed

- `.venv/Scripts/python.exe -m pytest -q tests/ui/test_beat_grid_selection.py -x`
  - 11 passed.

## Remaining issues

- Hands-on Windows UI confirmation is still recommended.
- To move a grid hidden entirely by Marks, the user must grab another uncovered
  division of the same grid.

## Suggested next task

Validate Mark-first overlap dragging and Beat Grid move undo/redo in the Windows
application, then resume the pending grandMA3 hardware/onPC validation.
