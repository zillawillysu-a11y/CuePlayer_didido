# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Allow each exported song to include only its selected Main and/or Button
content, while keeping allocation, MA2/MA3 XML, and the playlist UI aligned.

## What was implemented

- Added persisted per-song `main` and Button-lane selection. Missing selection
  data remains backward-compatible and means all eligible content is exported.
- Replaced the Content popup menu with the approved inline playlist layout:
  clicking the `x/y selected` summary expands a row directly below the song
  with checkboxes for Main and every Button lane that has marks.
- Added **Clear Selection** to the inline row. It unchecks the current song's
  Main and every Button while keeping that song enabled for export.
- Added **Select All** to restore all exportable Main/Button content for the
  current song.
- Changed Button Sequence labels from `Song_Mark 2` to `Mark 2`; export XML
  filenames still include the song name to avoid file collisions.
- Unlinked Console Setup's Fixed Macro import start from the View Layout Macro
  Pool start; each is now independently persisted and editable.
- Made show allocation reserve and assign only selected sequences; a
  Button-only song starts its first Button at that song's Sequence start.
- Updated MA2 and MA3 exports so excluded Main content produces no Main
  Sequence file, executor assignment, or Timecode Main Track.
- Kept selected Buttons in their own Sequence, executor, and Timecode tracks.

## Files changed

- `src/cueplayer/domain/models.py`
- `src/cueplayer/persistence/project_store.py`
- `src/cueplayer/exporters/common.py`
- `src/cueplayer/exporters/plan_from_song.py`
- `src/cueplayer/exporters/show_patch.py`
- `src/cueplayer/exporters/ma2/exporter.py`
- `src/cueplayer/exporters/ma3/exporter.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`

## Architecture decisions

- Selection belongs to `MaExportSettings` because it is show-export setup, not
  intrinsic song data.
- Planning remains the single source of truth: UI selection flows through
  `build_show_patch` and `plans_from_show_patch` before either exporter writes
  XML.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\ui\\test_show_patch_ma2_discovery.py tests\\exporters\\test_show_patch.py --basetemp .test-tmp-unlink-macros`
- Result: **25 passed**.

## Remaining issues

- A real MA2 import should verify a Button-only song's generated View and
  Timecode track placement alongside the existing full-song workflow.
- `startup_error.txt` was not modified.

## Suggested next task

Run a real MA2 import test for mixed selections (full song, Main-only,
Button-only), then improve any import-specific behavior found.
