# Sprint 8 follow-up — Video P0 PASS; Video Audio contiguous coverage

**Branch:** `cursor/sprint8-zoom-cue-video-state-028d`  
**Base:** `cursor/sprint8-cached-timeline-poster-028d` (PR #239)  
**PR:** #240  
**Prior tip (Video Mark-jump PASS):** `e9a2a313db48cc92b82070eadb2d8c479f4a2e8a`  
**Status:** Ready for Windows VIDEO AUDIO CONTIGUOUS COVERAGE validation  
**(do not merge #239/#240; do not claim Audio P0 solved until Windows passes)**

Preserved (do not regress): Timeline visuals, Mark seek-jump Video path
(`_canonical_seek`, discontinuous-seek floor reset, seek-jump stale protection,
decode scheduling), AudioEngine sample clock, Mark/Cue semantics, Export, zoom.

## Video P0 — PASS (Windows @ e9a2a31)

- Mark backward jump frames_at_250/500/1000ms = 5 / 11 / 22
- engine_advance_at_1000ms ≈ 1.002 s; last-present age ≈ 7.9 ms
- No `liveness_fail_single_frame`

**Freeze that Video path.** This change is Video Audio mixer scheduling only.

## Remaining failure — Video Track Audio coverage gaps

Measured @ e9a2a31:

- `video_audio.gap_fill = 422360` samples (~8.8 s of zero-fill @ 48 kHz)
- reject_nonfinite / reject_short = 0; PortAudio underflow/flags = 0
- Event ring: decode starts at ~1704 / 1713 / 1722 (9 s cadence) **after**
  gap_fill (~822 / ~4022 / ~4150 samples) — cable-unplug click = silence then
  abrupt return on publish

### Root cause

`_coverage_end()` used **global max** window end. After seeks, a disjoint
far-future cached window made `_maybe_prefetch()` believe ahead was healthy,
so the next **contiguous** cell was requested only after the current window
ended → measured gap-fill bursts.

### Fix

- Contiguous coverage frontier from the current source frame (integer samples)
- Overlap / ≤1-sample adjacency extends the frontier; disjoint future ignored
- In-flight suppresses duplicates but does **not** count as published coverage
- Prefetch next quantized window while contiguous ahead &lt; 36 s (before seam)
- `note_discontinuous_seek` on AudioEngine seek rebuilds local current+next
- Evict disjoint far windows before current / contiguous forward chain
- Off-RT PERF: frontier, ahead, request/publish mono, publish lead,
  steady vs cold-seek gap_fill deltas

No crossfade to hide steady-state gaps. No AudioEngine timing change.

## Windows validation

A. Continuous VA ≥2–3 min, ≥10 heavy boundaries, no seeks — no cable clicks;
   after warm-up `steady_gap_fill_delta` / `steady_gap_fill_samples` = 0;
   every next window publishes before first required sample (`publish_lead_seconds` &gt; 0).

B. Play → backward jump → ≥60 s continuous — no recurring 9 s gap.

C. Several Mark backward jumps — Video as responsive as e9a2a31.

READY FOR WINDOWS VIDEO AUDIO CONTIGUOUS COVERAGE VALIDATION
