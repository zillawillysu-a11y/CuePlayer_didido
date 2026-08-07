# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Make generated MA2 Song Views conform to the user's native
`VIEWVIEWVIEW.xml` reference, preserving the CuePlayer View layout after
import.

## What was implemented

- Compared every generated Widget against the user-exported native MA2 View.
- Changed Widget indices to one continuous sequence in native order; optional
  Pool widgets no longer start at index 8.
- Emit `has_focus` and `has_scrollfocus` together for every right-positioned
  Pool, so MA2 honors its x coordinate.
- Emit scroll attributes only for per-song Effects and Sequence, matching the
  native View XML; ordinary Pools no longer receive spurious scroll fields.
- Matched Mask Pool Data values to native MA2 output.
- Timecode Pool is now at least three cells wide (title + two built-ins), but
  can be extended to the right by dragging or editing its width.
- Added regression checks for continuous indices, focus flags, and absent
  generic scroll attributes.

## Files changed

- `src/cueplayer/exporters/ma2/exporter.py`
- `src/cueplayer/ui/ma2_view_layout.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_show_patch.py`
- `tests/ui/test_show_patch_ma2_discovery.py`

## Architecture decisions

- The user-supplied `VIEWVIEWVIEW.xml` is the compatibility reference for
  MA2 View serialization.
- Timecode has a minimum three-cell footprint, not a fixed three-cell maximum.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_show_patch.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-native-view-reference-2`
- Result: **21 passed**.

## Remaining issues

- Needs one real MA2 re-export/import verification using the newly generated
  View XML.
- Per-song Main/Button export content selection remains pending.
- `startup_error.txt` was not modified.

## Suggested next task

After MA2 verification, add expandable per-song Main/Button export content
selection.
