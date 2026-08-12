# Next task

**Status:** Awaiting user validation and packaging
**Type:** Long Video Clip alignment validation / Release 1.1.3
**Updated:** 2026-08-12

## Do this first

1. Add the long rehearsal video to the song.
2. Right-click its Video Clip and choose `Edit Video Clip…`.
3. Enter Source In `00:50:00.000`, Source Out `00:53:00.000`, and the desired
   Timeline Start.
4. Confirm Duration is 03:00.000 and validate picture plus embedded audio.
5. Test Ctrl+Z/Ctrl+Y and Clean Output.
6. Rebuild and smoke-test CuePlayer 1.1.3.

## Relevant files

- `src/cueplayer/ui/video_clip_dialog.py`
- `src/cueplayer/ui/timeline_widget.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_video_clip_dialog.py`
- `packaging/build_windows.ps1`
