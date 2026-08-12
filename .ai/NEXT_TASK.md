# Next task

**Status:** Awaiting user validation and packaging
**Type:** Cue List continuous Note editing / Release 1.1.3
**Updated:** 2026-08-12

## Do this first

1. Start playback near several closely spaced Cues.
2. Edit a Cue List Note and press Down to continue in the next Note row.
3. Keep typing while playback crosses another Cue.
4. Confirm the editor stays on the chosen row and its text is not truncated.
5. Rebuild and smoke-test CuePlayer 1.1.3.

## Relevant files

- `src/cueplayer/ui/cue_monitor_panel.py`
- `tests/ui/test_cue_list_note_edit_during_playback.py`
- `tests/ui/test_cue_list_note_arrow_navigation.py`
- `packaging/build_windows.ps1`
