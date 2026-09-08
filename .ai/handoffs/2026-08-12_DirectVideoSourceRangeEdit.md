# Direct Video source range edit handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Directly select a short source range from a long Video Clip.

## What was implemented

- Video context menu now opens Edit Video Clip.
- Fields: Timeline Start, Source In, Source Out, calculated Duration, Source Length.
- Time input supports H:MM:SS.mmm and shorter formats.
- Invalid/out-of-range source times are rejected.
- Apply uses existing undo and Video refresh paths.

## Files changed

- `src/cueplayer/ui/video_clip_dialog.py`
- `src/cueplayer/ui/timeline_widget.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_video_clip_dialog.py`

## Architecture decisions

- Existing VideoClip transform and shared playback clock remain canonical.

## Tests performed

Result: `13 passed`; four unrelated QMouseEvent deprecation warnings.

## Remaining issues

- Real long-video seek/audio/Clean Output validation remains.

## Suggested next task

Validate 50:00–53:00 against the real source, then rebuild 1.1.3.
