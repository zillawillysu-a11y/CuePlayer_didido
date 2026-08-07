# MA2 Per Song auxiliary Pools

## Task objective

Restore per-song numbering for all MA2 View Pool types, not only Effects and
Sequence.

## What was implemented

- Reinstated native scroll metadata for every `Per Song` Pool.
- Preserved scroll-free Fixed Pool XML.
- Added a second-song Camera versus fixed Groups regression test.

## Files changed

- `src/cueplayer/exporters/ma2/exporter.py`
- `tests/exporters/test_show_patch.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-08_Ma2PerSongAuxiliaryPools.md`

## Architecture decisions

- All Per Song View Pools receive a unique MA2 scroll range.

## Tests performed

- Focused MA2 exporter and Show Patch UI suite: 22 passed.

## Remaining issues

- Requires real MA2 import verification.
- Per-song content selection remains pending.
- `startup_error.txt` remains untouched.

## Suggested next task

After verification, implement per-song Main/Button content selection.
