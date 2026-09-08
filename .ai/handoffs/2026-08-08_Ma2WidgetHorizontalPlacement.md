# MA2 Widget horizontal placement

## Task objective

Ensure MA2 imports the CuePlayer View editor's right-positioned Pool windows
at their intended horizontal coordinates.

## What was implemented

- Compared the generated View against the supplied MA2 `POOLALL.xml`.
- Added `has_focus="true"` for every Widget with a non-zero `x` coordinate.
- Covered Sequence and MAtricks placement with a regression test.
- Fixed the Timecode Pool to its three-cell total footprint (title plus two
  MA2 built-in cells) and disabled its resize affordances.

## Files changed

- `src/cueplayer/exporters/ma2/exporter.py`
- `src/cueplayer/ui/ma2_view_layout.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_show_patch.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-08_Ma2WidgetHorizontalPlacement.md`

## Architecture decisions

- MA2 uses `has_focus` as a placement-enabling flag for right-positioned
  Widgets in imported Views.
- Timecode is a fixed three-cell MA2 control.

## Tests performed

- Focused MA2 exporter and Show Patch UI suite: 21 passed.

## Remaining issues

- Requires real MA2 re-export/import verification.
- Per-song content selection remains pending.
- `startup_error.txt` remains untouched.

## Suggested next task

After verification, implement per-song Main/Button content selection.
