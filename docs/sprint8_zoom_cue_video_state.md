# Sprint 8 follow-up — Mark seek-jump liveness + periodic Video Audio windows

**Branch:** `cursor/sprint8-zoom-cue-video-state-028d`  
**Base:** `cursor/sprint8-cached-timeline-poster-028d` (PR #239)  
**PR:** #240  
**Status:** Ready for Windows BACKWARD MARK-JUMP / PERIODIC VIDEO AUDIO WINDOW validation  
**(do not merge #239/#240; do not claim Video / Audio P0 solved)**

Preserved: Timeline mouse/static visuals, AudioEngine sample clock, Mark/Cue
timestamps, Export, Preview states, zoom anchor, no GPU / broad decoder redesign.

## Confirmed still good (do not regress)

- Normal Timeline scrub resume (~92–122 ms first frame)
- Forward play into dense Marks
- Continuous Audio stutter largely gone; PERF on/off parity
- PLAYBACK decode ~23–24 Hz

## A — Backward Mark-object jump froze Video

**Root cause:** Mark / cue / overview clicks called `playback.seek` only (no
scrub FINAL_LAND/RESUME). After a backward jump, in-flight play frames from the
old Song Time re-armed `_last_presented_song_seconds`, then new frames failed
`newer_already_presented`. One bootstrap-style present was not required for
liveness — progression stopped after the floor was wrong.

**Also:** Mark-object vs empty-Timeline previously used **different paths**
(Mark = bare seek; empty Timeline scrub = begin/end scrub + FINAL_LAND/RESUME).

**Fix:**
- `MainWindow._canonical_seek` for Mark / cue / overview / Timeline
  `seek_requested` (input source tagged: `mark_object` / `waveform` / `ruler` / …)
- `VideoSyncController.note_discontinuous_seek`: invalidate async, clear
  presentation floor, set `_min_present_seconds`, force schedule, drop
  `seek_jump_stale` frames during a short guard
- Liveness watch at 250/500/1000 ms (`video.seek_jump.frames_at_*ms`); fail if
  fewer than 2 presents by 1000 ms (first frame alone is not healthy)
- Dedicated `_seek_jump_mono` (must not share `_seek_after_mono`, which first-valid
  metrics clear)

## B — Periodic ~8–9 s Video Audio corruption

**Hypothesis (instrumented, not claimed solved until Windows):** 9 s heavy-window
step + float gather / lock-contended cache reads at publish boundaries.

**Fix / hardening:**
- Integer canonical source-sample indices in `_gather_samples`
- Older-window wins on overlap (stable ownership; no publish oscillation)
- Lock-free immutable `_rt_snapshot` for RT reads (callback never waits on worker)
- Pin playhead window against LRU eviction
- NaN/Inf / short PCM rejected → silence for that contribution only; counters
- Ring-buffer events (`window_decode_start/publish/eviction`, `owner_switch`,
  `callback_window_switch`, `boundary_delta`, `gap_fill`, `pcm_nonfinite_rejected`)
  flushed via PERF report (not every-callback file I/O)
- Audio callback always fully overwrites `outdata`

## Windows validation

### A — Backward Mark jump (×10)

1. Play beyond dense Marks, click a Mark object inside the dense region, wait ≥3 s.
2. Compare empty-Timeline click at the same target.
3. Pass: Video keeps advancing every time; `frames_at_1000ms` ≥ 2; no multi-second freeze.

### B — Periodic VA (wall clock ~07:45→08:35 style continuous play)

1. Continuous play ≥2 min Video Audio **enabled**, then **muted**; reopen song; repeat.
2. Correlate glitch wall times with `video_audio.event_ring` (publish / owner_switch /
   boundary_delta / eviction / gap_fill) and callback deadline misses.
3. Pass: no severe noise bursts; no repeated A/V stalls; callback exec &lt; period in
   steady play; no non-finite PCM; muted vs enabled both smooth.

READY FOR WINDOWS BACKWARD MARK-JUMP / VIDEO AUDIO GLITCH VALIDATION

READY FOR WINDOWS PERIODIC VIDEO AUDIO WINDOW VALIDATION
