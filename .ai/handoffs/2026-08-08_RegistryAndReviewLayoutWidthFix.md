# Export Registry / Review & Export Layout Width Fix

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Follow-up on the same-day page-layout reflow: user reported the Export
Registry's Telnet box + stat tiles were too wide (cutting off the Song
List), and Review & Export's Manual Pool Starts fields were visually
overlapping their labels and the left column was wider than needed.

## What was implemented

- **Export Registry**: `live_scan_box` (Telnet controls) changed to a
  compact 2-column grid, capped `setMaximumWidth(360)`. Left (Telnet) and
  middle (stat tiles) columns wrapped in container `QWidget`s with
  `setMaximumWidth` (360 / 200) since a bare layout can't be capped
  directly. `registry_table` now the sole `stretch=1` item, absorbing all
  remaining width.
- **Review & Export**: `review_left_column` wrapped in a container
  `QWidget` capped at `setMaximumWidth(340)`. Fixed the label/spinbox
  overlap bug in Manual Pool Starts (`manual_fields_grid` had no spacing at
  all) by adding explicit horizontal/vertical spacing; capped each seed
  spinbox at `setMaximumWidth(90)`. `review_table` now the sole
  `stretch=1` item.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`

## Architecture decisions

Container-widget + `setMaximumWidth` instead of stretch-ratio tuning —
stretch ratios alone don't hard-cap a panel's width on a large monitor.

## Tests performed

- `QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python.exe -m pytest tests/ui/test_show_patch_ma2_discovery.py tests/ui/test_setlist_folder_drag.py -q`: **32 passed** — pure layout change, no behavior touched.
- `compileall`: passed.
- No desktop GUI automation available — needs the user's own eyes to
  confirm the pixel result.

## Remaining issues

Same outstanding manual-verification checklist as prior 2026-08-08
handoffs — see `.ai/NEXT_TASK.md`.

## Suggested next task

User visually confirms the width fix, then works through the rest of the
manual-verification checklist (per-song Pool overrides, View Layout Follow
checkbox, Setlist drag into Export Queue) already queued in
`.ai/NEXT_TASK.md`.
