# Next task

**Status:** Awaiting user validation
**Type:** Validation (Beat Grid per-region color)
**Updated:** 2026-08-12

## Do this first

1. Create or edit two Beat Grid regions and assign different colors.
2. Confirm lines, translucent beat fills, hover, and selection use each color.
3. Save and reopen the project; confirm both colors persist.
4. Open an older project and confirm grids without individual colors still use
   the Display Settings color.

If these pass, resume the pending grandMA3 2.3.2 hardware/onPC validation.

## Relevant files

- `src/cueplayer/domain/models.py`
- `src/cueplayer/persistence/project_store.py`
- `src/cueplayer/ui/beat_grid_dialog.py`
- `src/cueplayer/ui/timeline_widget.py`
