# MA2 native View reference alignment

## Task objective

Align CuePlayer's generated MA2 View XML with the user-exported native
`VIEWVIEWVIEW.xml` reference.

## What was implemented

- Made Widget indices continuous in native ordering.
- Wrote both native focus attributes for right-positioned Pools.
- Limited scroll metadata to Effects and Sequence widgets.
- Matched native Mask Data values.
- Changed Timecode from fixed width to a resizable Pool with a three-cell
  minimum footprint.

## Files changed

- `src/cueplayer/exporters/ma2/exporter.py`
- `src/cueplayer/ui/ma2_view_layout.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_show_patch.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-08_Ma2NativeViewReferenceAlignment.md`

## Architecture decisions

- `VIEWVIEWVIEW.xml` is the MA2 serialization compatibility reference.
- Timecode minimum width is three total cells, including its title.

## Tests performed

- Focused MA2 exporter and Show Patch UI suite: 21 passed.

## Remaining issues

- Requires a real MA2 import verification.
- Per-song content selection remains pending.
- `startup_error.txt` remains untouched.

## Suggested next task

After verification, implement per-song Main/Button content selection.
