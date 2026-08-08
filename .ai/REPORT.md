# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Make MA Export review allocations clearer and editable, add Groups throughout
the export workflow, provide a drag-and-drop export queue, and save a durable
record of each export's Pool allocation. Follow-up: simplify the Songs & Pools
screen by removing the redundant sequence-chain banner and tightening rows.

## What was implemented

- Review & Export's five content checks are now interactive and synchronize
  bidirectionally with Console Setup.
- Unified the check-row backgrounds and reworked Manual Pool Starts so every
  numeric field has its own visible label.
- Added Groups allocation to Songs & Pools, Export Registry, and Review &
  Export in the order Sequence, Effects, Groups, Timecode, View, Song Macro.
- Fixed Group start calculations to respect the configured Group Pool Start.
- Added a Set List source tree and Export Queue. Drag individual songs,
  multi-select songs, or drag a folder; queue order is export order.
- Export now writes `ShowName_Export_Allocation.csv` (Excel-ready) and `.txt`
  beside the MA output, including all assigned ranges.
- Kept the configurable Show Name field in Console Setup and made the options
  grid two pairs wide so labels are legible.
- Removed the redundant Sequence chain banner from Songs & Pools and reduced
  main song rows to 38px.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`

## Architecture decisions

The Export Queue reuses persisted `export_song_ids`; it changes neither Song
membership nor Set List folders. CSV uses UTF-8 BOM for direct Excel opening
without an extra spreadsheet dependency.

## Tests performed

- `QT_QPA_PLATFORM=offscreen python -m pytest tests/ui/test_show_patch_ma2_discovery.py -q --basetemp .test-tmp-current-ui-4`: **14 passed**.
- `python -m compileall -q src/cueplayer/ui/show_patch_page.py`: passed.
- `ruff` is not installed in this virtual environment.

## Remaining issues

- User should visually validate live drag gestures in the desktop build and
  verify that the allocation reports match an actual MA export.
- `startup_error.txt` remains untouched.

## Suggested next task

Visually test the compact Songs & Pools layout and the Set List → Export Queue
drag/drop workflow, then perform one real MA2 export and check the report.
