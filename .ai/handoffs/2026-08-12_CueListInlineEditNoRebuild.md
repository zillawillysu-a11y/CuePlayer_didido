# Cue List inline edit no-rebuild handoff

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Stop delayed Cue List rebuilds from destroying Note editors and align the editor.

## What was implemented

- Note/Cue ID commits no longer schedule a full Cue List rebuild.
- Timeline/status still refresh and Undo/dirty behavior stays intact.
- Structural Mark changes still rebuild the list.
- Inline editor geometry is inset and vertically contained in its row.

## Files changed

- `src/cueplayer/ui/cue_monitor_panel.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_cue_list_note_edit_during_playback.py`
- `tests/ui/test_cue_list_note_no_rebuild.py`

## Architecture decisions

- Existing row items own inline text updates; rebuild only for structural changes.

## Tests performed

- Focused Cue List inline editor suite: 8 passed.

## Remaining issues

- Real playback stress-test remains.

## Suggested next task

Stress-test Note/Cue ID editing during playback, then package CuePlayer 1.1.3.
