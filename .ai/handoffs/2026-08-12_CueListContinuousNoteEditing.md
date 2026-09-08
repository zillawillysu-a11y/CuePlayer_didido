# Cue List continuous Note editing handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Prevent playback Cue changes from closing the adjacent Note editor selected by
keyboard navigation.

## What was implemented

- Playhead row-follow does not change Cue List selection while an editor is open.
- A navigation-pending guard covers the close/open gap between adjacent cells.
- NOW display updates remain live.

## Files changed

- `src/cueplayer/ui/cue_monitor_panel.py`
- `tests/ui/test_cue_list_note_edit_during_playback.py`

## Architecture decisions

- UI-only selection coordination; no domain or playback clock changes.

## Tests performed

- Focused Note editor/navigation suite: 4 passed.
- Playhead scroll suite: 2 passed before a reproducible native Qt stack overflow
  in its existing tiny-viewport test.

## Remaining issues

- Interactive validation during playback.
- Existing tiny-viewport Qt test stack overflow remains.

## Suggested next task

Validate Down-to-next-Note editing across a live Cue transition, then package
CuePlayer 1.1.3.
