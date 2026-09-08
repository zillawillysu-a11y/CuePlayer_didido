# Multiple Video Clips — Music-lane stand-in waveform only covered clip #1

Date: 2026-09-07. Branch: `technical-audit-0815-028d`. Baseline: `a77dc31`. Status: complete.

## User-reported bug

A Song's Video Track with 2+ Video Clips: the first clip's waveform displayed correctly;
the second and later clips' corresponding waveform (drawn "above" the clip, in the Music
lane) did not display, even though the Video Clip itself existed correctly on the
timeline.

## Audit (bug location clarified with user before fixing)

Two candidate waveform surfaces exist in the timeline:

1. **Video Track lane** — the per-clip blue rectangle's own inline waveform, painted by
   `TimelineWidget._paint_video_lane` → `_paint_video_clip_waveform`, backed by
   `VideoClipWaveformCache` (`media/video_clip_waveform.py`), which is keyed per `ClipWaveformKey`
   (path/mtime/source-in/out/duration/media_kind) and per-clip, with a shared
   `VideoWaveformArtifactStore` singleton keyed per media file (`media/video_waveform_artifact.py`).
   **Verified correct for N clips** by direct sync calls, real-threaded async builds (fake
   decoder), different files, same file at different positions, and clip deletion — see
   `tests/media/test_video_waveform_artifact.py::test_two_different_media_clips_both_get_waveforms`,
   `test_three_clips_not_only_first_has_waveform`, `test_two_clips_same_media_different_timeline_positions`,
   `test_deleting_one_clip_keeps_others_waveform` (all added this session, all pass on baseline too
   — this layer was never broken).
2. **Music lane video-audio stand-in** — when a Song has no music audio track, the Music
   lane shows the *video's own embedded audio* as a substitute waveform (feature in
   `main_window.py` / `TimelineWidget._paint_artifact_waveform`). **This is where the bug
   lived**, confirmed with the user via `AskUserQuestion`.

### Root cause

`TimelineWidget` held **one** mutable pair for this feature:
`self._artifact_wave: VideoWaveformArtifact | None` and
`self._artifact_wave_clip: VideoClip | None`. `MainWindow._primary_video_clip_for_standin()`
always picked the **first** eligible Video Clip on the song. `_paint_artifact_waveform`
mapped the *entire* Music-lane pixel range through that **single** clip's
`start_seconds`/`end_seconds`/`source_in_seconds`/`source_span_seconds` — any pixel column
outside that one clip's `[start, end)` span was masked to `NaN` (`in_clip` boolean mask) and
painted as a blank flat line. So clip #1's region always painted correctly (it was the only
clip ever bound), and clip #2, #3, … never got their own artifact/clip pair bound at all —
their Music-lane region stayed permanently blank, matching the report exactly ("above the
clip, waveform doesn't show, from the second clip onward").

The single-clip assumption was end-to-end: `MainWindow._primary_video_clip_for_standin`,
`TimelineWidget._artifact_wave`/`_artifact_wave_clip`/`_artifact_wave_complete`,
`TimelineWidget.set_artifact_waveform(art, clip, complete)`, and the entire async
scheduling state machine (`_video_standin_token`, `_video_standin_finished` Signal,
`_schedule_video_music_standin`, `_on_video_standin_finished`) only ever tracked **one**
clip's build at a time and never continued on to a second clip.

## Fix

### `TimelineWidget` (`src/cueplayer/ui/timeline_widget.py`)

- Replaced the single `_artifact_wave`/`_artifact_wave_clip`/`_artifact_wave_complete` trio
  with `self._artifact_waves: dict[str, tuple[VideoWaveformArtifact, VideoClip, bool]]`
  keyed by `VideoClip.id`.
- `set_artifact_waveform` → `set_artifact_waveform_for_clip(clip, art, *, complete=False)`:
  upserts/removes one clip's entry without touching any other clip's entry.
- Added `clear_artifact_waveform_for_clip(clip_id)` and `prune_artifact_waveforms(valid_ids)`
  (called from `refresh_video_clip_waveforms()`) so a deleted clip's stale entry cannot keep
  painting at its old position or leak forever.
- `clear_artifact_waveform()` now clears the whole dict (song switch / real audio bound).
- Added `_artifact_waves_any_coverage()` / `_artifact_waves_all_complete()` helpers and
  updated every gating site that previously read the single `_artifact_wave*` attrs
  (`_needs_waveform_overlay`, `_paint_audio_loading_overlay`, `_paint_waveform`,
  `set_audio_loading`, `set_audio`).
- `_paint_artifact_waveform` now takes an explicit `clip: VideoClip | None` parameter
  (instead of reading `self._artifact_wave_clip`) and is called **once per entry** in
  `self._artifact_waves` from `_paint_waveform` — each call only paints inside that one
  clip's own `[start, end)` span (the existing `in_clip` masking logic, unchanged). The
  "no valid pixels" flat-line fallback was narrowed to that clip's own x-range instead of
  drawing across the whole lane width (previously safe with only one clip; would have
  painted over a neighboring clip's already-drawn span otherwise).

### `MainWindow` (`src/cueplayer/ui/main_window.py`)

- Added `_standin_video_clips(song)` (all eligible clips, not just the first) and
  `_next_standin_clip_to_build(song)` (first eligible clip whose id is not yet in
  `self._video_standin_attempted_clip_ids` — that set is reset whenever the song id
  changes). `_primary_video_clip_for_standin` now delegates to
  `_standin_video_clips()[0]` and is kept only for the few "is there any standin-eligible
  clip at all" boolean checks.
- `_schedule_video_music_standin()` now asks `_next_standin_clip_to_build()` instead of
  always the first clip. `_audio_load_executor` still has a single worker, so only one
  clip's build ever runs at a time — after a clip's result lands,
  `_on_video_standin_finished` marks that clip attempted and calls
  `_schedule_video_music_standin()` again, walking every eligible clip in turn (disk-cache
  hits also chain forward synchronously instead of stopping after clip #1).
- `_video_standin_finished` Signal gained a `clip_id: str` field
  (`Signal(int, str, object)`); `_on_video_standin_finished(token, clip_id, result)` looks
  the clip up via `song.video_clip_by_id(clip_id)` and calls
  `set_artifact_waveform_for_clip`/`clear_artifact_waveform_for_clip` for **that** clip only
  — it no longer calls the old whole-lane `clear_artifact_waveform()` on a single clip's
  "no embedded audio" or build-exception outcome (that would have wiped every other
  already-built clip's waveform).
- The rare legacy whole-song `AudioBuffer` completion path (a single continuous buffer,
  inherently single-source) is now skipped when more than one Video Clip is standin-eligible,
  so it cannot silently wipe every other clip's per-id artifact entry via `set_audio()`.
- `_delete_video_clips` already called `refresh_video_clip_waveforms()` (now prunes stale
  `_artifact_waves` entries). Added the same `refresh_video_clip_waveforms()` +
  `_schedule_video_music_standin()` follow-up to `_split_video_clip` and
  `_duplicate_video_clip`, which previously only refreshed the Video-lane cache, not the
  Music-lane stand-in, for a newly created clip.
- Trim/move (`EditVideoClipsCommand._apply`) mutates the existing `VideoClip` object
  in place rather than replacing it, and `_paint_artifact_waveform` reads
  `clip.start_seconds`/`source_in_seconds`/`source_span_seconds` live at paint time — so no
  extra invalidation was needed for trim/move to stay correct; verified by inspection, not
  by a synthetic edit test (no drift risk since it is the same architecture that trim/move
  already relied on for the single-clip case).

## Why this needed touching "Music waveform architecture"

The task's default scope excluded Music waveform architecture unless the audit proved the
reported bug lived there. It does: this stand-in feature draws into the Music lane using
Music-lane-shaped code (`_paint_artifact_waveform`, `set_artifact_waveform`), and the user
confirmed (via `AskUserQuestion`) that the "waveform above the clip" they saw missing is
this feature, not the Video Track lane's own per-clip waveform (which was already correct).
Real Music audio (`self._audio` / `AudioBuffer`-backed) paint paths were not touched.

## Files changed

- `src/cueplayer/ui/timeline_widget.py` — per-clip `_artifact_waves` dict, painting, gating.
- `src/cueplayer/ui/main_window.py` — multi-clip stand-in scheduling/chaining.
- `tests/ui/test_waveform_high_zoom_outline.py` — updated one call site for the new
  `_paint_artifact_waveform(painter, art, clip, y0, y1, right)` signature (`clip=None`).
- `tests/media/test_video_waveform_artifact.py` — added 4 Video-lane multi-clip regression
  tests (this layer was already correct; tests lock it in).
- `tests/ui/test_video_music_standin_multi_clip.py` — new file, 4 regression tests for the
  actual bug (Music-lane stand-in), see below.

## Regression tests

`tests/ui/test_video_music_standin_multi_clip.py` (new):

- `test_two_clips_each_get_their_own_standin_span` — 2 different-media clips, both regions
  painted. **Fails on baseline** with `AttributeError: no attribute
  'set_artifact_waveform_for_clip'` (API didn't exist — old API structurally could not
  represent two independent clip spans).
- `test_three_clips_not_only_first_has_standin` — 3 clips, asserts none is blank.
- `test_deleting_first_clip_keeps_second_clip_standin` — delete clip A, clip B's span still
  paints; asserts `_artifact_waves` no longer contains clip A's id.
- `test_song_switch_clears_all_clip_standins` — switching song clears every clip's entry.

`tests/media/test_video_waveform_artifact.py` (new, lock in the already-correct layer):
`test_two_different_media_clips_both_get_waveforms`,
`test_three_clips_not_only_first_has_waveform`,
`test_two_clips_same_media_different_timeline_positions`,
`test_deleting_one_clip_keeps_others_waveform`.

## Test results

- `tests/media/test_video_waveform_artifact.py`, `test_video_clip_waveform.py`,
  `test_video_music_standin.py`, `tests/ui/test_video_waveform_continuous_paint.py`,
  `test_video_waveform_backdrop_revision.py`, `test_video_wave_during_play.py`,
  `test_video_wave_thread_safety.py`, `test_waveform_high_zoom_outline.py`,
  `test_video_music_standin_multi_clip.py` — **54 + 4 new = all pass**
  (`QT_QPA_PLATFORM=offscreen`, required — without it `TimelineWidget.show()` in
  `test_video_waveform_backdrop_revision.py` hangs waiting for a real window in this
  sandbox; unrelated to the fix).
- Broad related-UI sweep (video clip dialog/edit, hide video track, timeline splitter,
  video select-during-play, zoom/cue video state, timeline audio loading, standin cache,
  waveform play-defer, setlist media badges, cached timeline poster, edit-song-preserves-
  video, ltc source mode hydration): **88 passed**.
- `tests/application/test_show_session_service.py`, `tests/ports/test_show_host.py`
  (mock/stub `_schedule_video_music_standin`, signature-compatible): pass.

## Baseline failures encountered (confirmed pre-existing, NOT caused by this change)

Reproduced identically on baseline `a77dc31` (git-stashed the two source files, reran):

- `tests/ui/test_video_playhead_jank.py::test_play_uses_coarse_video_wave_and_wider_overscan`
  — `_view_width()` returns 500 instead of the resized 640 under `QT_QPA_PLATFORM=offscreen`.
- `tests/ui/test_mouse_static_backdrop_parity.py::test_video_lane_region_unchanged_on_scrub_press`
- `tests/ui/test_scrub_fallback_final_land.py::test_fallback_release_finalizes_when_left_button_up`
- `tests/ui/test_video_standin_cache.py::test_video_standin_restores_from_cache_on_reactivate`
  — `_audio_load_executor.submit` called (job dispatched) when the test expects a pure
  cache hit with no dispatch at all; this is a legacy-`AudioBuffer`-cache-path test whose
  expectation was already broken on baseline, unrelated to this session's `_artifact_waves`
  refactor (same failure, same call count, with and without the fix).

Per instructions, explicitly avoided running: `test_cue_list_playhead_scroll.py`, the known
Windows `test_video_sync` crash path, and anything touching a real PortAudio device.
`tests/ui/test_video_waveform_backdrop_revision.py` hangs without
`QT_QPA_PLATFORM=offscreen` (calls `TimelineWidget.show()`) — not a crash, just needs the
offscreen platform plugin in this sandbox; noted for future sessions running this suite.

## Out of scope (per instructions, not touched)

LTC waveform/clips, MTC thread, Playback Engine clock, MA exporter, version/copyright/About,
Windows title-bar Video freeze, NDI, persistence schema (clip identity — `VideoClip.id` —
already persists and survives save/reload; no schema change needed or made).
