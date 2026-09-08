# Keep Beat Grid above Video waveform handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Prevent Video waveform loading from visually hiding the BPM Grid.

## What was implemented

- Progressive waveform overlay now paints first.
- Beat Grid is restroked immediately afterward.
- Dynamic Mark/Grid/Loop/Playhead layers remain above both.

## Files changed

- `src/cueplayer/ui/timeline_widget.py`
- `tests/ui/test_beat_grid_video_overlay_order.py`

## Architecture decisions

- No data, hit-testing, playback, or static-cache changes.

## Tests performed

Result: `18 passed`; four unrelated QMouseEvent deprecation warnings.

## Remaining issues

- Real Video waveform visual smoke test remains.

## Suggested next task

Validate Grid visibility through Video load/play/zoom, then rebuild 1.1.3.
