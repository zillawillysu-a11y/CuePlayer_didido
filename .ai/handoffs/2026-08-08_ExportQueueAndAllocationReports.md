# Export Queue and Allocation Reports

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Improve the MA export selection/review UX and generate a durable Pool
allocation report after every export.

## What was implemented

- Added bidirectional Console Setup/Review content check synchronization.
- Added Groups to all export allocation tables and corrected its configured
  start arithmetic.
- Added the Set List source tree and drag/drop Export Queue, including whole
  folder and multi-song selection.
- Added Excel-ready CSV and TXT allocation reports after a successful export.
- Removed the redundant Sequence chain banner and compacted Songs & Pools rows.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`

## Architecture decisions

The queue persists via existing `MaExportSettings.export_song_ids`; no domain
model or exporter XML schema needed to change. Reports are simple files in the
chosen output folder and use UTF-8 BOM for Excel compatibility.

## Tests performed

- Offscreen MA export UI tests: **14 passed**.
- `compileall` passed for `show_patch_page.py`.

## Remaining issues

- Desktop drag gesture and a real MA2 report should be manually verified.
- `ruff` was unavailable in `.venv`.

## Suggested next task

Test Set List drag/drop and validate `ShowName_Export_Allocation.csv` and TXT
against one MA2 export.
