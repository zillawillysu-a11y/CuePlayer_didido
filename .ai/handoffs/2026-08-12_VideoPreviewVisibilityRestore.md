# Video Preview visibility restore handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Remember whether the embedded Video Preview Panel was open at shutdown.

## What was implemented

- Added machine-local Preview visibility persistence.
- Menu toggle saves immediately; UI session save records final visibility.
- Startup synchronizes the panel and View action.
- Missing setting defaults to visible for compatibility.

## Files changed

- `src/cueplayer/application/settings_service.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_video_preview_layout.py`

## Architecture decisions

- Machine UI preference only; no project schema or playback changes.

## Tests performed

- Video Preview layout/restore plus shutdown suite: 6 passed.

## Remaining issues

- Interactive restart validation remains.

## Suggested next task

Validate Preview off and on across restarts, then package CuePlayer 1.1.3.
