# MA2 Preset Cue Timecode index

## Task objective

Keep Timecode Main Cue targets correct when the MA2 installer adds Cue 0.5
named `Preset`.

## What was implemented

- Offset each Timecode target only if the installed Preset sorts before it.
- Passed the optional Preset ID through the show-install Timecode generation.
- Added a Cue 1 target regression test.

## Files changed

- `src/cueplayer/exporters/ma2/exporter.py`
- `tests/exporters/test_show_patch.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-08_Ma2PresetCueTimecodeIndex.md`

## Architecture decisions

- MA2 numeric Cue ordering, not Store command order, determines Timecode cue
  index targets when fractional Cues are present.

## Tests performed

- Focused MA2 show-patch and Timecode suite: 21 passed.

## Remaining issues

- Needs MA2 verification with Preset enabled.
- Per-song content selection remains pending.
- `startup_error.txt` remains untouched.

## Suggested next task

Implement persisted per-song Main/Button export content selection.
