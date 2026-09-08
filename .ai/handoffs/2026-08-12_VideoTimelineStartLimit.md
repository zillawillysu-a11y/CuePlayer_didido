# Video Timeline Start limit handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Keep a mistyped Timeline Start from placing a Video Clip beyond the song.

## What was implemented

- Edit Video Clip rejects Timeline Start later than the current song duration.
- The invalid value never reaches the existing clip transform/update path.
- Added boundary tests for later-than-end rejection and exact-end acceptance.

## Files changed

- `src/cueplayer/ui/video_clip_dialog.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_video_clip_dialog.py`

## Architecture decisions

- MainWindow passes Song duration into the dialog; Song and playback clock
  behavior remain unchanged.

## Tests performed

- Video Clip dialog/edit/select suite: 15 passed, four existing warnings.

## Remaining issues

- Interactive validation with the user's long video remains.

## Suggested next task

Try one invalid Timeline Start, then validate the 50:00–53:00 source range and
package CuePlayer 1.1.3.
