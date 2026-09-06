# LTC Generator Clips — Phase 2 (playback wiring: LTC audio + MTC + display)
Date: 2026-09-06. Branch: technical-audit-0815-028d.
Upstream: origin/cursor/technical-audit-0815-028d.
Status: complete (Phase 2 only; no clip editing UI / exporter / preview work).

## Task objective
Wire the Phase-1 per-song `clip_generator` domain into playback:

- Generated LTC audio only inside the song's LTC Generator Clips
  (`output_tc = clip.start_timecode + (position - clip.timeline_start)`).
- Outside every clip: **no LTC** (silence on the LTC bus), **no MTC**, and the
  timecode display shows `--:--:--:--` (never a song-start fallback).
- MTC shares the *same* clip mapping as the LTC audio; entering a clip
  re-anchors MTC (full-frame dump + quarter frames at the mapped TC);
  leaving a clip stops MTC output.
- `full_track_generator`, `striped_file`, legacy `auto`, and explicit `off`
  keep today's behavior (regression-tested).

Out of scope (per user): Timeline clip create/drag/trim UI, clip start-TC
editor, MA2/MA3 exporters, export preview, multi-timecode show architecture.

## What was implemented

### `src/cueplayer/playback/mtc_output.py`
- New optional TC provider: `set_tc_provider(provider)` where
  `provider: (position_seconds) -> Timecode | None`. `None` provider keeps the
  legacy single `start_timecode` timebase.
- `tick()` now resolves each quarter-frame group's TC through
  `_tc_at_locked()` (provider or timebase). A `None` result sends **no**
  quarter frames for that group (index still advances — no burst on resume).
- Resuming from a no-TC stretch re-anchors (`_reset_qf_locked` + full frame)
  so receivers latch the new mapping.
- `_send_full_frame_locked()` uses the provider; no full frame is emitted at
  positions with no TC source.
- `timecode_at()` falls back to the timebase when the provider yields `None`
  (engine display does not rely on it in clip mode).

### `src/cueplayer/playback/audio_engine.py`
- `_resolved_ltc_mode()`: domain `resolved_song_ltc_source_mode` for the
  active song; no song → legacy resolution from project settings.
- `_uses_clip_ltc()`: `ltc_enabled` + resolved `clip_generator`.
- `_uses_generated_ltc()`: now resolved-mode based. Legacy `auto` songs
  resolve exactly as before (generator + `ltc_generator_enabled` gate);
  explicit `full_track_generator` behaves like the legacy generator
  (still gated by project `ltc_enabled` / `ltc_generator_enabled`); explicit
  `off` / `striped_file` stop the full-track generator; `clip_generator`
  never uses the full-track pcm (mutual exclusion).
- Per-clip LTC PCM cache (`_ltc_clip_table`: `(timeline_start, timeline_end,
  pcm)` per clip), built async on the existing `_ltc_executor`, keyed on
  (sample rate, fps, clip set). `_clip_ltc_chunk()` mixes overlapping clip
  slices; outside clips the chunk is silence. Fallback before the async
  table is ready renders overlapping clips with throwaway
  `LtcPlaybackCursor`s (O(chunk), same mapping).
- `_ltc_chunk()` routes clip songs to `_clip_ltc_chunk()` before any
  file-source/generator path; LTC gain applies.
- `_ltc_bus_active()`: clip mode uses the dedicated LTC bus (or the legacy
  3.5mm stereo-leg `LTC` route) — same wiring rules as the full-track
  generator.
- File-LTC suppression in clip mode (stripes cannot coexist with clips):
  `_song_file_ltc_channel()`, `_file_ltc_channel()`,
  `_resolved_file_ltc_channel()`, `_effective_ltc_source_channel()`,
  `_decode_source_channel()` all return `None` when resolved mode is
  `clip_generator`; `_sync_mtc_to_file_ltc()` never mirrors a decoded file
  stripe in clip mode. Music bed is not stripe-stripped for clip songs.
- MTC source install + re-anchoring:
  - `_mtc_clip_provider()` → closure over a snapshot of `song.ltc_clips`
    using domain `ltc_timecode_at` (single source of truth; no duplicate TC
    math in the engine).
  - `_install_mtc_tc_source()` called from `set_song`, `set_song_timebase`,
    `apply_audio_settings`, `refresh_song_ltc_routing`; re-anchors when the
    TC source identity changes.
  - `_mtc_tc_source_key(pos)` (`("base",)` / `("none",)` / `("clip", id)`)
    tracked in `_mtc_source_key`; `_mtc_tick()` re-anchors (full frame when a
    mapping is active, silence outside) when the playhead crosses into/out of
    a clip; `seek()` updates the key so the next tick doesn't double-anchor.
- `output_timecode_state()`: clip mode shows the mapped TC inside clips and
  `--:--:--:--` outside (never the song-start / generator fallback). Legacy
  modes unchanged.
- Cache invalidation (`_invalidate_ltc_cache`) also clears the clip table;
  `pause()` keeps the stream alive when a clip table is active (video-only
  songs with clip LTC).
- A–B loop wrap (`_assemble_looped_ltc`) goes through `_ltc_chunk()`, so
  loops automatically respect clip boundaries.

### `tests/playback/test_ltc_clip_playback.py` (new, 20 tests)
- In-clip chunk == per-clip `generate_ltc_pcm` slice; silence before/after;
  straddling chunk split at the exact clip start.
- Decoded TC inside clips matches `clip.start_timecode + offset`
  (incl. 01:00:01:15 at +1.5 s).
- Multiple clips restart TC at each clip's start; second clip independent of
  the first.
- Backward TC range (later clip starting before the earlier clip's TC) plays
  correctly in playback (exporter warnings are later scope).
- Adjacent clips: the later clip owns the shared boundary position.
- Fallback renderer (cache not ready) matches the cached mapping.
- Display: mapped TC inside, `--:--:--:--` outside (explicit check that the
  song-start fallback is *not* shown), seek updates the display.
- MTC: silent outside clips; full-frame re-anchor + QFs inside clip A at the
  mapped TC; silence in the inter-clip gap; re-anchor to clip B's start TC.
- Legacy single-timebase MTC unchanged without a provider.
- Legacy `auto`+generator full-track pcm byte-identical; explicit
  `full_track_generator` like legacy; explicit `off` silent; clip song with
  generator project settings uses clips only (no full-track pcm); clip mode
  ignores a striped file (no bus feed, no music stripping); clip display
  independent of project `ltc_source`; LTC gain applies to clip LTC;
  no-song legacy resolution.

## Files changed
- `src/cueplayer/playback/audio_engine.py` (clip mapping wiring; ~230 lines
  added incl. cache + helpers)
- `src/cueplayer/playback/mtc_output.py` (TC provider; +~50 lines)
- `tests/playback/test_ltc_clip_playback.py` (new)

## Architecture decisions
- Domain `ltc_clips` helpers remain the **single source** of the TC mapping;
  the engine only ships cached PCM slices and passes the domain mapping into
  MTC as a provider (no duplicate TC arithmetic in the playback layer).
- MTC re-anchoring reuses the existing `on_seek`/full-frame machinery;
  clip-boundary detection is a cheap source-key comparison per 4 ms tick.
- Provider runs under the MTC lock and is pure (snapshot list + domain
  function) — no engine lock → no deadlock.
- Clip PCM is built per-clip (not one full-track buffer), so TC restarts are
  exact and the table stays small; async build mirrors the existing
  full-track cache pattern (published under `engine._lock`).
- Explicit `full_track_generator` is gated by project
  `ltc_enabled`/`ltc_generator_enabled` (conservative: an explicit song mode
  cannot force output when the project generator switch is off).

## Tests performed
- New: `tests/playback/test_ltc_clip_playback.py` — **20/20 passed**.
- Regression: `tests/playback` (excl. `test_video_sync.py`), `tests/timecode`,
  `tests/domain`, `tests/routing` — **462 passed, 3 failed**; all 3 failures
  (`test_ndi_probe`, 2× `test_song_use_left_ltc`) **also fail on the clean
  Phase-1 tree** (verified via `git stash`) → pre-existing, unrelated.
- `tests/playback/test_video_sync.py` — 82 passed, 1 failed
  (`test_duplicate_decoded_frame_is_not_reemitted`), identical on the clean
  tree; an intermittent Windows AV in the video-decoder thread also occurred
  in a combined run on the clean tree (fragile media area, not touched here).
- `tests/ui` — 60 passed up to a pre-existing font-rendering failure
  (`test_clock_fit_narrow_panel`), identical on the clean tree.

## Remaining issues
- Pre-existing test failures (unrelated): NDI probe DLL-path test,
  `song_use_left_ltc` routing tests (route-map assertion), video-sync
  flake/AV, clock font-fit test.
- `MtcOutput.tick()` QF groups straddling a clip boundary may send up to 2 TC
  frames of the *previous* clip's TC (quantization of the 8-QF group);
  receivers re-latch on the full frame at the boundary.
- No UI yet to create/edit clips — Phase 3. `refresh_song_ltc_routing()` is
  the intended hook to call after clip edits (already re-arms caches, MTC
  source, routing, stream).
- Exporter handling of out-of-clip marks / warnings — Phase 3 (per
  `.ai/NEXT_TASK.md`).

## Suggested next task
See `.ai/NEXT_TASK.md` — LTC Generator Clips Phase 3: per-song clip
create/edit UI (timeline), validation display, then MA2/MA3 exporter wiring.
