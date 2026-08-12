# Next task

**Status:** Awaiting user validation and packaging
**Type:** Video Clip validation / Release 1.1.3
**Updated:** 2026-08-12

## Do this first

1. Open Edit Video Clip and enter a Timeline Start later than the song end.
2. Confirm the warning reports the song length and the existing clip remains.
3. Enter Source In `00:50:00.000`, Source Out `00:53:00.000`, and a valid
   Timeline Start.
4. Confirm picture, embedded audio, Ctrl+Z/Ctrl+Y, and Clean Output.
5. Rebuild and smoke-test CuePlayer 1.1.3.

## Relevant files

- `src/cueplayer/ui/video_clip_dialog.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_video_clip_dialog.py`
- `packaging/build_windows.ps1`
