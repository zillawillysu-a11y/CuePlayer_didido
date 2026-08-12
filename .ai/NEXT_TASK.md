# Next task

**Status:** Awaiting user validation and packaging
**Type:** Bugfix validation / Release 1.1.3
**Updated:** 2026-08-12

## Do this first

1. Play a song and begin typing in a blank Cue List Note.
2. Keep the editor open while playback crosses one or more Cue boundaries.
3. Confirm the uncommitted text remains visible, then press Enter and confirm it
   is stored.
4. Rebuild CuePlayer 1.1.3 and repeat the smoke test in the packaged executable.

## Separate known test issue

`tests/ui/test_cue_list_playhead_scroll.py::test_tiny_cue_list_keeps_playhead_row_visible`
currently produces a Windows PySide6 C-level stack overflow and should be
diagnosed as a separate task.

## Relevant files

- `src/cueplayer/ui/cue_monitor_panel.py`
- `tests/ui/test_cue_list_note_edit_during_playback.py`
- `packaging/build_windows.ps1`
