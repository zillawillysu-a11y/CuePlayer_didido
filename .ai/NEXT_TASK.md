# Next task

**Status:** Awaiting user validation
**Type:** Validation (Timeline / Beat Grid)
**Updated:** 2026-08-12

## Do this first

Open the Windows application and validate:

1. Drag a position where a Mark exactly overlaps a Beat Grid division; the Mark
   must move whether the magnet is enabled or disabled.
2. Drag a different Beat Grid division without a Mark on it; the whole Beat Grid
   region must move.
3. Press Ctrl+Z and Ctrl+Y after moving the Beat Grid.

If these pass, resume the pending grandMA3 2.3.2 hardware/onPC validation.

## Explicitly out of scope

- Playback clock behavior
- MA2/MA3 XML changes
- Persistence schema changes

## Relevant files

- `src/cueplayer/ui/timeline_widget.py`
- `tests/ui/test_beat_grid_selection.py`
