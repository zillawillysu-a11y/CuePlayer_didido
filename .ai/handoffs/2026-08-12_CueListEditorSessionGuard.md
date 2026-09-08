# Cue List editor session guard handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Protect keyboard and mouse Note editor handoffs from playback row-follow.

## What was implemented

- Added explicit Cue List editor-session tracking.
- Delegate open/close signals control session lifetime.
- Editable-cell mouse press protects the handoff before the previous editor closes.
- Up/Down handoff remains protected until the adjacent editor is open.
- Playback can update NOW without changing Cue List selection during editing.

## Files changed

- `src/cueplayer/ui/cue_monitor_panel.py`
- `tests/ui/test_cue_list_note_edit_during_playback.py`

## Architecture decisions

- UI-only fix; no playback or project schema changes.

## Tests performed

- Focused Cue List Note playback/navigation suite: 5 passed.

## Remaining issues

- Real playback stress-test remains.

## Suggested next task

Stress-test Up/Down and mouse Note switching across several live Cue changes,
then package CuePlayer 1.1.3.
