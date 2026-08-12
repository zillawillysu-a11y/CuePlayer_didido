# Mark Track header Add switch handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Make Mark creation by clicking the left Track name an explicit opt-in behavior.

## What was implemented

- Project-global switch defaults off.
- Header left-click adds only when enabled.
- Header right-click menu exposes a checked toggle.
- State persists; legacy projects default off.
- Cursor affordance follows the switch.

## Files changed

- `src/cueplayer/domain/models.py`
- `src/cueplayer/persistence/project_store.py`
- `src/cueplayer/ui/timeline_widget.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_mark_lane_rename.py`
- `tests/persistence/test_mark_lane_header_add.py`

## Architecture decisions

- Project-wide behavior; existing Mark creation signal remains canonical.

## Tests performed

- Header behavior and persistence suites: 9 passed.

## Remaining issues

- Interactive wording/behavior validation remains.

## Suggested next task

Validate off/on header clicks and persistence, then package CuePlayer 1.1.3.
