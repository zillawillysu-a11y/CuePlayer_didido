# Export Queue Clear-Queue Bug Fix and Regression Tests

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Follow up on `.ai/NEXT_TASK.md`: verify the Set List → Export Queue
drag/drop workflow (single song, multi-select, whole folder, reorder, Clear
Queue) and confirm queue order matches every downstream table and the
allocation report, then do a real MA2 export and compare.

## What was implemented

Real mouse drag gestures in the desktop app and a live grandMA2
export/compare are outside this session's toolset (web Browser only, no
desktop GUI automation, no MA2 host reachable). Instead:

- Verified by code trace that `ExportQueueList` (`song_pick`) row order is
  the single source that `_checked_songs()` reads, which flows into
  `build_show_patch()` → `self._slots` → playlist table, Export Registry,
  Review & Export, and `_write_export_allocation_report()` — so all five
  surfaces are order-consistent by construction.
- Found and fixed a real bug: **Clear Queue did nothing**. `_set_all_songs(False)`
  cleared `export_song_ids` but left the `song_pick` widget's items checked;
  `_write_ui_to_settings()` re-derives `export_song_ids` from checked widget
  items on every `refresh()`, so the very next refresh silently restored the
  full queue. Fixed in `src/cueplayer/ui/show_patch_page.py` by calling
  `self._rebuild_song_pick()` (repopulates the widget from the now-empty
  `export_song_ids`) before `refresh()` in that branch.
- Added 4 regression tests in `tests/ui/test_show_patch_ma2_discovery.py`
  covering: Clear Queue actually empties the queue and survives a later
  refresh; folder drag (`SetlistExportTree.selected_song_ids()`) returns all
  songs in a category in order; multi-select drag appends without
  duplicating an already-queued song; and reordering the queue (simulating
  the `InternalMove` drag) propagates to `export_song_ids`, `_slots`, and the
  written CSV together.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`

## Architecture decisions

`ExportQueueList` stays the single source of truth for queue
membership/order; `_rebuild_song_pick()` is now the only path used to
repopulate it from `export_song_ids`, closing the race that let
`_write_ui_to_settings()` clobber a just-cleared queue.

## Tests performed

- `QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python.exe -m pytest tests/ui/test_show_patch_ma2_discovery.py -q --basetemp .test-tmp-export-queue-review2`: **18 passed**.
- `./.venv/Scripts/python.exe -m compileall -q src/cueplayer/ui/show_patch_page.py tests/ui/test_show_patch_ma2_discovery.py`: passed.

## Remaining issues

- User still needs to: visually confirm the compact Songs & Pools layout in
  the running desktop app; manually drag one song / a multi-selection / a
  whole folder into the Export Queue and drag-reorder within it; click Clear
  Queue and confirm it now visibly empties; run one real MA2 export and diff
  `ShowName_Export_Allocation.csv`/`.txt` against the actual Pools MA2
  created.
- `ruff` still not installed in `.venv`.
- `startup_error.txt` and `.codex-test-tmp/` left untouched.

## Suggested next task

User performs the manual desktop + real-MA2-export verification above (see
`.ai/NEXT_TASK.md`). Report back exact mismatches, if any, for a follow-up
fix; otherwise close out spec item 34 (Export Queue) as verified.
