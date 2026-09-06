# Focusrite key/pitch drift capture analysis
Date: 2026-09-06. Branch: technical-audit-0815-028d.
Upstream: origin/cursor/technical-audit-0815-028d.

## Task objective
Analyze three captured performance reports from actual Focusrite USB ASIO
playback (interface: Scarlett 4i4) to determine whether the reported audible
KEY/pitch drift is caused by sample-rate mismatch, DAC/ASIO clock drift,
callback timing, or another source. No clock correction.

## What was analyzed
Three `manual-dump` performance reports (baseline / seek / loop) from one
live stream: stream_epoch=6, device 32 (Focusrite USB ASIO), 48000 Hz,
1024 frames/callback, 2 channels. Parsed each 512-row `audio.timing` ring and
the cross-dump spans (same epoch, continuous). Log:
`.cache/audio-diagnostics/audio-perf-20260906-175723-354.txt`.

## Findings
- Rate chain consistent: source/processing/callback/stream_reported all
  48000 Hz; music_resample_ready=True; played MP3 is natively 48 kHz (no
  resample); stream requested and reported 48000 (no rate fallback).
- ASIO hardware sample clock stable vs host clock: per-segment dac/host
  0.999907–1.000217; cross-dump +12.3 ppm (11.9 s) and -34.9 ppm (7.2 s);
  per-callback 21.332/21.348 ms vs nominal 21.333 ms. No consistent trend.
- Measured clock error (~35 ppm max = ~0.06 cents) is ~two orders of magnitude
  below the ~5800–11600 ppm needed for an audible 10–20 cent key drift.
- No underflow: status_flags=0, underflow=0, queued latency constant 45.92 ms.
- Legacy UI position vs DAC shadow: constant ~74–96 ms offset (queued audio),
  not drift.
- Individual late callbacks present: max adjacent dac residual ~21.1 ms in
  every dump = single-callback thread/GIL stalls, not clock drift.

## Diagnostic caveat (important)
`Audio callback continuity` counters (callback_count, interval mean/max,
deadline_miss) are cumulative since engine creation; `_open_output_stream`
resets only `_cb_last_mono` and `_cb_expected_period`. So
`callback_count=17395`, `interval_mean=16.5 ms`, `deadline_miss=6119 (35%)`
mix all 6 stream epochs and are misleading for the current stream. The
per-ring `audio.timing` data is the correct signal and is clean. Counter-reset
on stream open is a small planned follow-up fix.

## Conclusion
The captures do NOT show a sample-clock cause for the key drift. The ASIO
output is a clean, stable 48 kHz with no underflow and no measurable DAC
drift. The perceived key/pitch drift is not explained by the ASIO sample
rate or DAC clock in this data.

## Remaining hypotheses (ranked)
1. Drift is slow/time-varying; the ~30 s window between dumps is too short —
   need a longer continuous capture to see a dac/host trend.
2. Pitch error is in the Focusrite hardware/DSP/monitoring path, not the ASIO
   sample clock — need a driver-independent physical loopback pitch test.
3. The perceived "drift" is actually a timing/LTC desync, not audio pitch.

## Next step (interface model now known: Scarlett 4i4)
Physical loopback: play a known 440.000 Hz sine at constant level, route
Focusrite line-out -> line-in (or a second ASIO device), record 30–60 s, and
measure the output frequency over time. Plus a 5–10 minute continuous
playback capture with periodic report dumps. No clock correction until after
these results.

## Files changed
- .ai/REPORT.md (full analysis)
- .ai/handoffs/2026-09-06_FocusriteKeyDriftAnalysis.md (this file)
- .ai/NEXT_TASK.md (next step updated to physical loopback + long capture)
- analysis scripts in .cache/ (analyze_perf_rings.py, cross_dump_drift.py)

## Architecture decisions
Diagnosis only; no playback/clock/rate/routing/UI change. AudioEngine remains
the sole playback clock; driver timestamps are not physical latency. All
product constraints remain intact.

## Tests performed
Parsed the three dumps' audio.timing rings and cross-dump spans (scripts in
.cache/). Verified the played MP3 is natively 48 kHz (PyAV). Confirmed
counter-reset semantics by reading AudioEngine.__init__ and
_open_output_stream. No runtime execution, no production change.

## Remaining issues
- Root cause of the key drift not confirmed; physical loopback + longer
  continuous capture required before any clock decision.
- Audio callback continuity counters are cumulative since engine creation
  (diagnostic defect); planned small fix to reset them on stream open.
- No public clock change made.
