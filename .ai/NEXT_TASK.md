# Next task

**Status:** Awaiting user stress-test and packaging
**Type:** Cue List inline editing / Release 1.1.3
**Updated:** 2026-08-12

## Do this first

1. Play through several closely spaced Cues.
2. Type Notes and repeatedly use Up/Down to move between rows.
3. Directly click other Note and Cue ID cells while playback continues.
4. Confirm editors stay aligned, do not close, and text is preserved.
5. Recheck Video Preview visibility across restart.
6. Rebuild and smoke-test CuePlayer 1.1.3.

## Relevant files

- `src/cueplayer/ui/cue_monitor_panel.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_cue_list_note_edit_during_playback.py`
- `tests/ui/test_cue_list_note_no_rebuild.py`
- `packaging/build_windows.ps1`
