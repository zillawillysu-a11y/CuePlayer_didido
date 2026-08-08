# Drag From the Real Setlist Sidebar Into Export Queue

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

User feedback: Songs & Pools had its own duplicate "Set List (drag songs or
a folder)" tree as the Export Queue's drag source, but the app already has a
real Setlist sidebar on the left. Remove the duplicate; make the real
Setlist the drag source instead.

## What was implemented

- New `src/cueplayer/ui/dnd_mime.py` — shared `EXPORT_SONG_IDS_MIME` MIME
  type constant, importable by both `main_window.py` and
  `show_patch_page.py` without either importing the other (avoids a
  circular import, since `main_window.py` already imports `ShowPatchPage`).
- `SetlistWidget` (`main_window.py`) now emits `EXPORT_SONG_IDS_MIME`:
  - `mimeData()` override adds it from `self._drag_song_ids` (already
    computed by `startDrag()` for song-row drags); internal reorder logic
    (`dropEvent()`) is unaffected since it reads `self._drag_song_ids`
    directly, never MIME data — purely additive.
  - New `_song_ids_under_folder(folder_row)` helper scans a folder's row
    block for song ids in on-screen order.
  - `_start_folder_drag()` now also attaches all song ids under that folder
    to its manually-built `QMimeData`, so a whole-folder drag queues every
    song in it.
- `ShowPatchPage` (`show_patch_page.py`): deleted `SetlistExportTree`, the
  `setlist_export_source` tree, "Add Selected →" button, and their support
  methods. "Set List → Export Queue" group box is now just "Export Queue"
  with a hint to drag from the Setlist panel. `ExportQueueList` (drop
  target) needed no changes — it already keys only on the MIME format, not
  the source widget.
- Test coverage:
  - `tests/ui/test_show_patch_ma2_discovery.py`: new
    `test_export_queue_accepts_a_song_ids_drop_from_the_setlist_panel`
    dispatches a real `QDropEvent` at `ExportQueueList.dropEvent` (replacing
    the old test that used the now-deleted tree).
  - `tests/ui/test_setlist_folder_drag.py`: new
    `test_song_row_drag_mime_data_carries_export_song_ids` and
    `test_folder_drag_mime_data_carries_all_song_ids_in_folder` prove
    `SetlistWidget` actually produces the payload for both cases.

## Files changed

- `src/cueplayer/ui/dnd_mime.py` (new)
- `src/cueplayer/ui/main_window.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `tests/ui/test_setlist_folder_drag.py`

## Architecture decisions

`SetlistWidget` remains the single real Setlist source of truth; no second
song list is maintained anywhere. `ExportQueueList` stays source-agnostic,
only checking for the shared MIME format.

## Tests performed

- `QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python.exe -m pytest tests/ui/test_show_patch_ma2_discovery.py tests/ui/test_setlist_folder_drag.py -q`: **25 passed**.
- `compileall` on all touched files: passed.
- Ran a full `tests/ui` suite pass for extra confidence; it hit a
  pre-existing `Windows fatal exception: stack overflow` partway through,
  plus two pre-existing failures in `test_setlist_category_click.py`.
  Confirmed via `git stash` (temporarily reverting to the pre-session code)
  that both reproduce identically without this change — pre-existing,
  suite-scale issue, out of scope here.

## Remaining issues

- Real mouse drag gestures (Setlist → Export Queue: single song,
  multi-select, whole folder) and a real MA2 export still need manual
  verification in the desktop app — no desktop GUI automation or MA2 host is
  reachable from this session.
- The pre-existing full-suite stack overflow and the two
  `test_setlist_category_click.py` failures need separate investigation
  (likely thread/resource accumulation across many `MainWindow()`
  instantiations in one pytest process) — not part of this change.
- `startup_error.txt` and `.codex-test-tmp/` left untouched.

## Suggested next task

User manually drags a song, a multi-selection, and a whole folder from the
real Setlist sidebar into the Export Queue in the running desktop app, then
does one real MA2 export and compares
`ShowName_Export_Allocation.csv`/`.txt` against actual Pool numbers.
