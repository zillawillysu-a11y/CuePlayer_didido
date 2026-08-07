# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Make MA2 retain the CuePlayer View editor's horizontal Pool positions during
View import.

## What was implemented

- Compared the current generated `0150_View_3.xml` with the MA2-native
  `POOLALL.xml` supplied by the user.
- Found that MA2 renders non-zero Widget `x` coordinates at the left edge
  unless the Widget is marked `has_focus="true"`.
- Automatically mark every right-positioned Pool as focusable, including the
  Sequence Pool and optional pools such as MAtricks.
- Preserved the current Macro handling and the editable 16×8 View geometry.
- Added a regression test for Sequence and MAtricks widgets placed right of
  the left edge.
- Fixed the Timecode Pool to MA2's three-cell footprint: one title cell and
  two built-in Timecode cells.  It can be moved but not resized.

## Files changed

- `src/cueplayer/exporters/ma2/exporter.py`
- `src/cueplayer/ui/ma2_view_layout.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_show_patch.py`
- `tests/ui/test_show_patch_ma2_discovery.py`

## Architecture decisions

- MA2 View XML is a native compatibility format: `has_focus` is required for
  a Widget's non-zero horizontal placement, rather than merely UI focus.
- The Timecode Pool is a fixed three-cell MA2 control, not a resizable
  numbered Pool window.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_show_patch.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-nonzero-x-focus`
- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_show_patch.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-layout-focus-timecode-2`
- Result: **21 passed**.

## Remaining issues

- A new CuePlayer export and MA2 View import is required to verify the fix.
- Per-song Main/Button export content selection remains pending.
- `startup_error.txt` was not modified.

## Suggested next task

After MA2 verification, add expandable per-song Main/Button export content
selection.
