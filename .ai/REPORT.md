# Multiple Video Clips — Music-lane stand-in waveform only covered clip #1

Date: 2026-09-07. Branch: `technical-audit-0815-028d`. Baseline: `a77dc31`. Status: complete.

## Task objective

Bugfix: a Song's Video Track with 2+ Video Clips only showed the Music-lane
video-audio stand-in waveform over the first clip's region; clip #2+ regions stayed
blank even though the clips existed correctly on the timeline. Audit first, confirm
root cause, minimal fix, regression tests, no packaging.

## Root cause (confirmed with user via clarifying question before fixing)

Two waveform surfaces exist. The Video Track lane's own per-clip waveform
(`_paint_video_clip_waveform` / `VideoClipWaveformCache`) was already correct for any
number of clips — verified with new regression tests, not touched.

The bug was in the **Music-lane video-audio stand-in** (shown when a Song has no music
audio track, substituting the video's own embedded audio as the Music-lane waveform):
`TimelineWidget` held a single mutable `_artifact_wave`/`_artifact_wave_clip` pair, and
`MainWindow._primary_video_clip_for_standin()` always picked the first eligible clip.
`_paint_artifact_waveform` masked every pixel outside that one clip's `[start, end)`
span to NaN (blank). Clips #2+ never got their own artifact/clip binding at all.

## Fix

- `TimelineWidget`: replaced the single pair with
  `self._artifact_waves: dict[clip_id, (artifact, clip, complete)]`;
  `set_artifact_waveform_for_clip` / `clear_artifact_waveform_for_clip` /
  `prune_artifact_waveforms`; `_paint_artifact_waveform` now takes an explicit `clip`
  param and is called once per dict entry, each painting only its own clip's span.
- `MainWindow`: `_schedule_video_music_standin` / `_on_video_standin_finished` now walk
  every eligible clip in turn (one build at a time, on the existing single-worker
  executor) instead of stopping after the first clip; the `_video_standin_finished`
  Signal now carries the `clip_id` so results are routed to the right clip's entry
  instead of a single global slot.
- Full detail, all edge cases (same-media clips, delete, split/duplicate, trim/move
  live-reference correctness, legacy AudioBuffer path guard): see
  `.ai/handoffs/2026-09-07_MultiVideoClipMusicStandinWaveformFix.md`.

## Files changed

- `src/cueplayer/ui/timeline_widget.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_waveform_high_zoom_outline.py` (updated call site for new signature)
- `tests/media/test_video_waveform_artifact.py` (+4 Video-lane multi-clip lock-in tests)
- `tests/ui/test_video_music_standin_multi_clip.py` (new, +4 regression tests for the bug)

## Test results

- Targeted + broad video/waveform/timeline UI suites: **146 passed** total across the
  runs in this session (`QT_QPA_PLATFORM=offscreen` required — without it one file's
  `TimelineWidget.show()` hangs waiting for a real window in this sandbox).
- 4 pre-existing baseline failures encountered, reproduced identically with the fix
  reverted (git-stashed) — confirmed **not** caused by this change: 
  `test_video_playhead_jank.py::test_play_uses_coarse_video_wave_and_wider_overscan`,
  `test_mouse_static_backdrop_parity.py::test_video_lane_region_unchanged_on_scrub_press`,
  `test_scrub_fallback_final_land.py::test_fallback_release_finalizes_when_left_button_up`,
  `test_video_standin_cache.py::test_video_standin_restores_from_cache_on_reactivate`.
- Skipped per instruction: `test_cue_list_playhead_scroll.py`, known Windows
  `test_video_sync` crash path, real PortAudio device tests.

## Out of scope (not touched)

LTC waveform/clips, MTC thread, Playback Engine clock, MA exporter, version/copyright/
About, Windows title-bar Video freeze, NDI, persistence schema.

## Manual verification checklist for the user

1. Create Video Clips A, B, C on one Song's Video Track using 3 different video files
   with no music audio track on the song — confirm all three show a Music-lane
   waveform above their own span.
2. A and B using the same video file — both still show their own span correctly.
3. Move clip B — its Music-lane span moves with it.
4. Trim clip B — its Music-lane span's content stays correctly mapped to the new
   trim/offset.
5. Delete clip A — B and C's Music-lane waveforms remain.
6. Save → Close → Reload the project — all clips' Music-lane waveforms still show.
