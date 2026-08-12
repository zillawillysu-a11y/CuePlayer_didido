# Next task

**Status:** Awaiting user validation and packaging
**Type:** Mark Track header Add switch / Release 1.1.3
**Updated:** 2026-08-12

## Do this first

1. Left-click several Mark Track names and confirm no Mark is added by default.
2. Right-click a Track name and enable `Click Track Header to Add Mark`.
3. Confirm left-click now adds the selected Mark Type at the playhead.
4. Save/reopen and confirm the project remembers the switch.
5. Recheck Cue List Note editing during playback.
6. Rebuild and smoke-test CuePlayer 1.1.3.

## Relevant files

- `src/cueplayer/domain/models.py`
- `src/cueplayer/persistence/project_store.py`
- `src/cueplayer/ui/timeline_widget.py`
- `tests/ui/test_mark_lane_rename.py`
- `tests/persistence/test_mark_lane_header_add.py`
- `packaging/build_windows.ps1`
