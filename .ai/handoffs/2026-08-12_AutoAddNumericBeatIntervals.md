# Auto Add numeric beat intervals handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Offer Auto Add Marks intervals as numeric beat counts 0.5 through 8.

## What was implemented

- Interval choices: 0.5, 1, 2, 3, 4, 5, 6, 7, 8.
- Values are floats representing beats.
- Placement spacing uses beat duration, including true half-beat spacing.
- Selected start line and Bars limit behavior are retained.

## Files changed

- `src/cueplayer/ui/beat_grid_dialog.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_auto_add_marks_intervals.py`

## Architecture decisions

- Numeric domain meaning replaces encoded presentation strings.

## Tests performed

Result: `21 passed` across interval, domain, and Beat Grid UI tests.

## Remaining issues

- Windows visual/placement validation remains.

## Suggested next task

Validate 0.5/1/4/8 intervals and Bars limit, then rebuild CuePlayer 1.1.3.
