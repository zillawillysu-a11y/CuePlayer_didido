# MA2 Fixed Pool Start scrolling

## Task objective

Make Fixed MA2 View Pools display their configured non-one Pool Start.

## What was implemented

- Added scroll metadata for any Pool whose effective start differs from 1.
- Preserved per-song scroll allocation.
- Added coverage for Fixed Groups 41 and Fixed Macros 191.

## Files changed

- `src/cueplayer/exporters/ma2/exporter.py`
- `tests/exporters/test_show_patch.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-08_Ma2FixedPoolStartScroll.md`

## Architecture decisions

- Fixed means shared across songs, not pinned to Pool 1.

## Tests performed

- Focused MA2 exporter and Show Patch UI suite: 22 passed.

## Remaining issues

- Requires real MA2 import verification.
- Per-song content selection remains pending.
- `startup_error.txt` remains untouched.

## Suggested next task

After verification, implement per-song Main/Button content selection.
