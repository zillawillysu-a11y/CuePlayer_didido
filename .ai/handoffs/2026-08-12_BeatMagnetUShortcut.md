# Beat magnet U shortcut handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Use keyboard U to toggle Beat Grid magnet snapping with synchronized feedback.

## What was implemented

- U QShortcut routes through MainWindow to Timeline.
- Timeline toggles magnet state and its active chip together.
- Text/numeric editor focus suppresses U.

## Files changed

- `src/cueplayer/ui/main_window.py`
- `src/cueplayer/ui/timeline_widget.py`
- `tests/ui/test_setup_mode_shortcut.py`

## Architecture decisions

- Timeline remains the single magnet state source.

## Tests performed

Result: `4 passed` for combined S/U shortcut behavior.

## Remaining issues

- Windows physical-key smoke test remains.

## Suggested next task

Validate S/U keyboard and typing behavior, then rebuild CuePlayer 1.1.3.
