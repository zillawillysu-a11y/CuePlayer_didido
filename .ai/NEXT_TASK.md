# Next task

**Status:** Awaiting user validation and packaging
**Type:** Auto Add Marks validation / Release 1.1.3
**Updated:** 2026-08-12

## Do this first

1. Right-click a Beat Grid line and open Auto Add Marks.
2. Confirm Interval contains exactly `0.5, 1, 2, 3, 4, 5, 6, 7, 8`.
3. Test 0.5, 1, 4, and 8 and confirm spacing begins at the selected line.
4. Confirm the Bars field still limits how many measures are generated.
5. Rebuild and smoke-test CuePlayer 1.1.3.

## Relevant files

- `src/cueplayer/ui/beat_grid_dialog.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_auto_add_marks_intervals.py`
- `packaging/build_windows.ps1`
