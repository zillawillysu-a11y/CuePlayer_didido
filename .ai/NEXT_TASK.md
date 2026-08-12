# Next task

**Status:** Awaiting user validation and packaging
**Type:** Feature validation / Release 1.1.3
**Updated:** 2026-08-12

## Do this first

1. Right-click a Beat Grid and enable `BPM Grid Lock`.
2. In Setup mode, confirm clicking still selects/seeks to the grid.
3. Confirm normal drag and Ctrl-dragging either endpoint cannot modify it.
4. Confirm Edit, Auto Add Marks, and Delete remain available.
5. Undo/redo the Lock toggle, save/reopen, and confirm the state persists.
6. Unlock it, confirm dragging returns, then rebuild CuePlayer 1.1.3.

## Relevant files

- `src/cueplayer/domain/models.py`
- `src/cueplayer/domain/undo.py`
- `src/cueplayer/persistence/project_store.py`
- `src/cueplayer/ui/timeline_widget.py`
- `src/cueplayer/ui/main_window.py`
