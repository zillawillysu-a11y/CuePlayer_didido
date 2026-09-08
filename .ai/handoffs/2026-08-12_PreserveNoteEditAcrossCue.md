# Preserve Note edit across Cue changes

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Keep uncommitted Cue List Note text while playback advances to another Cue.

## What was implemented

- NOW row highlighting no longer mutates Note cell BackgroundRole.
- The custom Note delegate already handles selection painting, so appearance is
  retained without triggering editor model reloads.
- Added an editor-level playback crossing regression test.

## Files changed

- `src/cueplayer/ui/cue_monitor_panel.py`
- `tests/ui/test_cue_list_note_edit_during_playback.py`

## Architecture decisions

- Fixed the redundant UI model write rather than changing playback or forcibly
  committing partial user input.

## Tests performed

- New playback crossing test: 1 passed.
- Existing Note arrow navigation tests: 2 passed.
- Existing tiny Cue List viewport test crashes in PySide6 with stack overflow;
  recorded separately.

## Remaining issues

- Real Windows playback validation remains.
- Independent tiny-viewport stack overflow remains.

## Suggested next task

Validate live Note editing across multiple Cues, then rebuild version 1.1.3.
