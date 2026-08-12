# Next task

**Status:** Awaiting user validation
**Type:** Validation (Beat Grid Edit undo)
**Updated:** 2026-08-12

## Do this first

1. Right-click a Beat Grid and change its color in Edit Beat Grid.
2. Press Ctrl+Z; the old color must return.
3. Press Ctrl+Y; the new color must return.
4. Change color, BPM, and Duration together and verify they undo/redo as one step.
5. Save/reopen and confirm the final state persists.

## Relevant files

- `src/cueplayer/domain/undo.py`
- `src/cueplayer/ui/main_window.py`
- `tests/domain/test_beat_grid.py`
