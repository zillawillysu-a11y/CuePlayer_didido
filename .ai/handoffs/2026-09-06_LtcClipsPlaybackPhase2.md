# LTC Generator Clips — Phase 2 (playback wiring: LTC audio + MTC + display)
Date: 2026-09-06. Branch: technical-audit-0815-028d.
Upstream: origin/cursor/technical-audit-0815-028d.
Status: complete (Phase 2 only; no clip editing UI / exporter / preview work).

## Task objective
Wire the Phase-1 per-song `clip_generator` domain into playback:

- Generated LTC audio only inside the song's LTC Generator Clips
  (`output_tc = clip.start_timecode + (position - clip.timeline_start)`).
- Outside every clip: no LTC (silence), no MTC, display shows `--:--:--:--`
  (never a song-start fallback).
- MTC shares the same clip mapping as the LTC audio; entering a clip
  re-anchors MTC (full-frame + quarter frames at the mapped TC); leaving a
  clip stops MTC.
- `full_track_generator`, `striped_file`, legacy `auto`, explicit `off`
  keep today's behavior (regression-tested).

Out of scope (per user): timeline clip create/drag/trim UI, clip start-TC
editor, MA2/MA3 exporters, export preview, multi-timecode show architecture.

## What was implemented

### `src/cueplayer/playback/mtc_output.py`
- Optional TC provider: `set_tc_provider(provider)` with
  `provider: (position_seconds) -> Timecode | None`; `None` provider keeps
  the legacy single timebase.
- `tick()` resolves each QF group's TC via `_tc_at_locked()` (provider or
  timebase); `None` sends no QF for that group (index still advances — no
  burst on resume).
- Resuming from a no-TC stretch re-anchors (`_reset_qf_locked` + full frame).
- `_send_full_frame_locked()` uses the provider; no full frame where the
  mapping yields `None`.
- `timecode_at()` falls back to the timebase when the provider yields `None`.

### `src/cueplayer/playback/audio_engine.py`
- `_resolved_ltc_mode()` — domain `resolved_song_ltc_source_mode` for the
  active song; no song → legacy project-settings resolution.
- `_uses_clip_ltc()` — `ltc_enabled` + resolved `clip_generator`.
- `_uses_generated_ltc()` — resolved-mode based; legacy `auto` unchanged;
  explicit `full_track_generator` still gated by project `ltc_enabled` /
  `ltc_generator_enabled`; explicit `off` / `striped_file` stop the
  full-track generator; `clip_generator` never uses the full-track pcm.
- Per-clip LTC PCM cache `_ltc_clip_table: tuple[(start_frame, end_frame,
  pcm), …]`, async on the existing `_ltc_executor`, keyed on
  (sample rate, fps, clip set). `_clip_ltc_chunk()` mixes overlapping clip
  slices; silence outside clips. Fallback before the table is ready renders
  overlapping clips with throwaway `LtcPlaybackCursor`s (O(chunk)).
- `_ltc_chunk()` routes clip songs to `_clip_ltc_chunk()` before any
  file-source/generator path; LTC gain applies.
- `_ltc_bus_active()` — clip mode uses the dedicated LTC bus (or the legacy
  3.5mm `LTC` stereo leg), like the full-track generator.
- File-LTC suppression in clip mode (stripes can't coexist with clips):
  `_song_file_ltc_channel()`, `_file_ltc_channel()`,
  `_resolved_file_ltc_channel()`, `_effective_ltc_source_channel()`,
  `_decode_source_channel()` return `None`; `_sync_mtc_to_file_ltc()` never
  mirrors a file stripe in clip mode; music bed is not stripe-stripped.
- MTC: `_mtc_clip_provider()` (closure over a snapshot of `song.ltc_clips`
  using domain `ltc_timecode_at` — single source of truth),
  `_install_mtc_tc_source()` from `set_song` / `set_song_timebase` /
  `apply_audio_settings` / `refresh_song_ltc_routing`;
  `_mtc_tc_source_key(pos)` (`("base",)` / `("none",)` / `("clip", id)`)
  tracked in `_mtc_source_key`; `_mtc_tick()` re-anchors when the playhead
  crosses into/out of a clip; `seek()` updates the key (no double-anchor).
- `output_timecode_state()` — clip mode: mapped TC inside clips,
  `--:--:--:--` outside (never the song-start fallback); legacy modes
  unchanged.
- `_invalidate_ltc_cache()` also clears the clip table; `pause()` keeps the
  stream alive when a clip table is active (video-only songs).
- A–B loop wrap goes through `_ltc_chunk()` → loops respect clip boundaries.

### `tests/playback/test_ltc_clip_playback.py` (new, 20 tests)
In-clip/out-of-clip chunks (byte-identical to per-clip `generate_ltc_pcm`
slices), decoded mapped TC (incl. +1.5 s → 01:00:01:15), TC restart per
clip, backward TC range in playback, adjacent-clip boundary (later clip
wins), fallback renderer, display mapped / `--:--:--:--` (no song-start
fallback), seek updates, MTC silent outside + full-frame re-anchor at clip
A/B, legacy MTC timebase unchanged, legacy `auto`+generator full-track
byte-identical, explicit `full_track_generator` / `off` behavior, clip song
with generator project settings, clip mode ignores striped file (no bus
feed, no music stripping), display independent of project `ltc_source`,
LTC gain applies, no-song legacy resolution.

## Files changed
- `src/cueplayer/playback/audio_engine.py`
- `src/cueplayer/playback/mtc_output.py`
- `tests/playback/test_ltc_clip_playback.py` (new)

## Architecture decisions
- Domain `ltc_clips` helpers stay the **single source** of the TC mapping;
  the engine ships cached PCM slices and passes the domain mapping into MTC
  as a provider (no duplicate TC arithmetic in playback).
- MTC re-anchoring reuses the existing `on_seek`/full-frame machinery;
  clip-boundary detection is a cheap source-key comparison per 4 ms tick.
- Provider runs under the MTC lock and is pure (snapshot + domain function)
  → no engine lock, no deadlock.
- Per-clip PCM (not one full-track buffer) makes TC restarts exact; async
  build + publish under `engine._lock` mirrors the existing full-track
  cache pattern.
- Explicit `full_track_generator` is gated by project
  `ltc_enabled` / `ltc_generator_enabled` (conservative).

## Tests performed
- New: `tests/playback/test_ltc_clip_playback.py` — **20/20 passed**.
- Regression: `tests/playback` (excl. `test_video_sync.py`) + `tests/timecode`
  + `tests/domain` + `tests/routing` — **462 passed, 3 failed**; all 3
  failures (`test_ndi_probe`, 2× `test_song_use_left_ltc`) also fail on the
  clean Phase-1 tree (verified via `git stash`) → pre-existing.
- `tests/playback/test_video_sync.py` — 82 passed, 1 failed
  (`test_duplicate_decoded_frame_is_not_reemitted`), identical on the clean
  tree; an intermittent Windows AV in the video-decoder thread also occurred
  in a combined run on the clean tree (fragile media area, not touched).
- `tests/ui` — 60 passed up to a pre-existing font-rendering failure
  (`test_clock_fit_narrow_panel`), identical on the clean tree.

## Remaining issues
- Pre-existing test failures (unrelated): NDI probe DLL-path test,
  `song_use_left_ltc` routing tests, video-sync flake/AV, clock font-fit.
- MTC QF groups straddling a clip boundary may send up to 2 TC frames of
  the previous clip's TC (8-QF group quantization); receivers re-latch on
  the boundary full frame.
- No clip create/edit UI yet — Phase 3. `refresh_song_ltc_routing()` is the
  hook to call after clip edits (re-arms caches, MTC source, routing,
  stream).
- Exporter handling of out-of-clip marks / warnings — Phase 3.

## Suggested next task
LTC Generator Clips Phase 3: per-song clip create/edit UI (timeline),
validation display (errors block, warnings show), then MA2/MA3 exporter
wiring — see `.ai/NEXT_TASK.md`.
