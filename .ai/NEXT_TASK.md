# Next task

**Status:** Awaiting user validation and packaging
**Type:** Bugfix validation / Release 1.1.3
**Updated:** 2026-08-12

## Do this first

1. Run CuePlayer from source and Rename a Mark Track from its timeline header.
2. Confirm the new name appears immediately without switching songs.
3. Rebuild CuePlayer 1.1.3 with `packaging/build_windows.ps1`.
4. Launch the packaged executable and repeat the Rename smoke test.

## Relevant files

- `src/cueplayer/ui/timeline_widget.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_mark_lane_rename.py`
- `packaging/build_windows.ps1`
