# Next task

**Status:** Awaiting user validation
**Type:** Validation (Timeline / Beat Grid resize)
**Updated:** 2026-08-12

## Do this first

In Setup mode on Windows, validate:

1. Hold Ctrl and drag the first Beat Grid boundary; only Start should change.
2. Hold Ctrl and drag the last boundary; only End should change.
3. Ctrl+Z and Ctrl+Y should undo and redo each Duration adjustment.
4. Dragging an internal uncovered division without Ctrl should still move the
   complete region.
5. A Mark/Grid overlap should still prioritize the Mark.

If these pass, resume the pending grandMA3 2.3.2 hardware/onPC validation.

## Relevant files

- `src/cueplayer/domain/undo.py`
- `src/cueplayer/ui/main_window.py`
- `src/cueplayer/ui/timeline_widget.py`
- `tests/domain/test_beat_grid.py`
- `tests/ui/test_beat_grid_selection.py`
