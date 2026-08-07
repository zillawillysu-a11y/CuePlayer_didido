# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Prevent the optional MA2 Main Cue `0.5 Preset` from shifting every generated
Timecode Main Cue target.

## What was implemented

- Identified that MA2 sorts the stored `0.5 Preset` before Cue 1, while the
  Timecode XML addresses the cue's sequence index rather than its Cue ID.
- Passed the optional Preset Cue ID into show-install Timecode generation.
- Offset only Main Timecode targets that occur after the Preset Cue ID; Cue 1
  therefore targets sequence index 2 when Preset 0.5 is enabled.
- Kept single-song exports and exports without the Preset unchanged.
- Added a regression assertion for the Timecode target of Cue 1.

## Files changed

- `src/cueplayer/exporters/ma2/exporter.py`
- `tests/exporters/test_show_patch.py`

## Architecture decisions

- MA2 Timecode target indices must account for cue IDs inserted by the
  installer when MA2's numeric sort order places them before regular cues.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_show_patch.py tests\\exporters\\test_latency_compensation.py --basetemp .test-tmp-preset-cue-timecode-3`
- Result: **21 passed**.

## Remaining issues

- Requires real MA2 verification with `Add Main Cue named Preset` enabled.
- Per-song Main/Button export content selection remains the next feature.
- `startup_error.txt` was not modified.

## Suggested next task

Add persisted per-song Main/Button export content selection, then filter the
Registry, Review, Sequence, and Timecode output accordingly.
