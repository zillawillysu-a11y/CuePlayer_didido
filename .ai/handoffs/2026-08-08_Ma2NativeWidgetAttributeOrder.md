# MA2 native Widget attribute order

## Task objective

Make an imported MA2 Song View retain the Macro Pool's configured position.

## What was implemented

- Matched the attribute sequence written by MA2's own `S1View.xml` export.
- Wrote Macro focus fields and `x` position before widget dimensions.
- Added an XML serialization regression assertion.

## Files changed

- `src/cueplayer/exporters/ma2/exporter.py`
- `tests/exporters/test_show_patch.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-08_Ma2NativeWidgetAttributeOrder.md`

## Architecture decisions

- MA2's View importer is treated as order-sensitive for Widget XML attributes, even though regular XML consumers should not be.

## Tests performed

- Focused MA2 exporter and Show Patch UI suite: 19 passed.

## Remaining issues

- Needs one real MA2 re-export/import verification.
- Per-song content selection is still pending.
- `startup_error.txt` remains untouched.

## Suggested next task

After verification, implement per-song Main/Button content selection.
