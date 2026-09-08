# Setup mode S shortcut handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Use keyboard S to toggle Mark movement/Setup mode with synchronized UI feedback.

## What was implemented

- MainWindow owns an S QShortcut.
- Timeline owns the actual state transition and S chip active state.
- Text/numeric input focus suppresses the shortcut.

## Files changed

- `src/cueplayer/ui/main_window.py`
- `src/cueplayer/ui/timeline_widget.py`
- `tests/ui/test_setup_mode_shortcut.py`

## Architecture decisions

- One Setup state source in Timeline; shortcut is routing only.

## Tests performed

Result: `2 passed` for shortcut wiring/state/indicator/input focus.

## Remaining issues

- Windows physical-key smoke test remains.

## Suggested next task

Validate S toggling and Note typing, then rebuild CuePlayer 1.1.3.
