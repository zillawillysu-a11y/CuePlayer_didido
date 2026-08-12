# Next task

**Status:** Awaiting user validation
**Type:** Validation (Timeline / Beat Grid)
**Updated:** 2026-08-12

## Do this first

Open the Windows application and validate:

1. Move a Beat Grid, press Ctrl+Z, then Ctrl+Y; its complete region should
   return to the old position and then the new position.
2. In Setup mode, overlap a Mark with a Beat Grid division. With magnet enabled,
   dragging the overlap should move the Mark and snap it to Beat Grid divisions.
3. Disable magnet and drag the same overlap; the complete Beat Grid region
   should move instead.
4. Confirm right-click still exposes both Mark actions and the Beat Grid submenu.

If these pass, resume the blocked grandMA3 2.3.2 hardware/onPC validation
documented in the prior reports and handoffs.

## Explicitly out of scope

- Playback clock behavior
- MA2/MA3 XML changes
- Persistence schema changes

## Relevant files

- `src/cueplayer/domain/undo.py`
- `src/cueplayer/ui/main_window.py`
- `src/cueplayer/ui/timeline_widget.py`
- `tests/domain/test_beat_grid.py`
- `tests/ui/test_beat_grid_selection.py`
