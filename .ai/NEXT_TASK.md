# Next task

**Status:** Awaiting user validation and packaging
**Type:** Rendering validation / Release 1.1.3
**Updated:** 2026-08-12

## Do this first

1. Open a song containing a BPM Grid and add a Video clip.
2. Wait until the Video waveform finishes loading.
3. Confirm BPM Grid lines and translucent fills stay visible while paused,
   playing, zooming, and selecting the Video clip.
4. Confirm Mark and Grid hover/selection highlights still appear above it.
5. Rebuild and smoke-test CuePlayer 1.1.3.

## Relevant files

- `src/cueplayer/ui/timeline_widget.py`
- `tests/ui/test_beat_grid_video_overlay_order.py`
- `packaging/build_windows.ps1`
