# Next task

**Status:** Awaiting user validation and packaging
**Type:** Video Preview visibility / Release 1.1.3
**Updated:** 2026-08-12

## Do this first

1. Turn off View > Video Preview Panel.
2. Close and reopen CuePlayer; confirm Preview stays closed.
3. Turn it on, close and reopen; confirm Preview returns.
4. Recheck continuous Cue List Note editing during playback.
5. Rebuild and smoke-test CuePlayer 1.1.3.

## Relevant files

- `src/cueplayer/application/settings_service.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_video_preview_layout.py`
- `packaging/build_windows.ps1`
