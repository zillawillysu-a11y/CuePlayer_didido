# Focusrite USB ASIO "key/pitch drift" capture analysis
Date: 2026-09-06. Branch: technical-audit-0815-028d.
Upstream: origin/cursor/technical-audit-0815-028d.
Status: analysis complete (diagnosis only; no code or clock changes made).
Source: three manual `Tools -> Write Performance Report` dumps from an actual
Focusrite USB ASIO playback session, plus ring analysis. Log:
`.cache/audio-diagnostics/audio-perf-20260906-175723-354.txt`.

## Task objective
The user heard the music KEY/pitch drift during Focusrite USB ASIO playback
(interface model: Focusrite Scarlett 4i4). Analyze the three captured
performance reports (baseline / seek / loop) to determine whether the drift
is caused by a sample-rate mismatch, a DAC/ASIO clock drift, callback
timing, or something else. No clock correction is to be applied.

## What was analyzed
All three dumps are the same open stream: `stream_epoch=6`, `device_index=32`
(Focusrite USB ASIO), 48000 Hz, 1024 frames per callback, 2 output channels.
Each dump carries a 512-row `audio.timing` callback ring (host_monotonic,
current_time, dac_time, frames, rates, status). I parsed the rings, the
cross-dump spans (same epoch, continuous stream), the reported stream rate,
and the music file native rate.

## Findings (all from the current stream's per-ring data)
1. Rate chain is consistent — no mismatch, no resample.
   `source_rate = processing_rate = callback_rate = stream_reported.samplerate
   = 48000 Hz`; `music_resample_ready=True`. The played MP3
   (`Media/0806_彩排音檔/拉麵公子/S7_拉麵公子.mp3`) is natively 48 kHz, so
   nothing is resampled. The stream was requested at 48000 and PortAudio
   reported 48000 (no driver rate-negotiation fallback).
2. The ASIO hardware sample clock is accurate and stable vs the host clock.
   Per-segment dac_time/host_monotonic ratios: 0.999907–1.000217.
   Cross-dump (continuous, same epoch): +12.3 ppm over 11.946 s and
   -34.9 ppm over 7.216 s; per-callback dac interval 21.332/21.348 ms vs the
   nominal 21.333 ms. No consistent trend (signs alternate), i.e. no slow
   drift visible in this window.
3. The measured clock error is far below the audible threshold.
   Worst case ~35 ppm = ~0.06 cents. An audible key drift of ~10 cents needs
   a sustained ~5800 ppm, and ~20 cents ~11600 ppm. The measured error is
   roughly two orders of magnitude smaller than what could produce the
   reported audible drift.
4. No underflow / dropout. `status_flags_or=0`, `output_underflow_count=0`,
   queued latency constant at 45.92 ms (= `stream_reported.latency`).
5. Legacy UI position vs DAC presentation shadow agree to ~74–96 ms
   (about 3–4.5 blocks) — a constant queued-audio offset, not a drift.
6. There ARE individual late callbacks: the max adjacent dac-time residual is
   ~21.1 ms in every dump (exactly one 1024-frame period). These are single
   callback thread/GIL stalls, not clock drift.

## Important diagnostic caveat (misleading counters)
The report's `Audio callback continuity` section is NOT a current-stream
measurement. `callback_count`, `interval_sum/mean`, `interval_max`,
`exec_sum/mean/max`, `deadline_miss_count` are only initialised in
`AudioEngine.__init__`; `_open_output_stream` resets only
`_cb_last_mono` and `_cb_expected_period`. So `callback_count=17395`,
`interval_mean_s=0.016506` (16.5 ms < 21.33 ms nominal) and
`deadline_miss_count=6119/17395 (35%)` accumulate across all 6 stream epochs
for the whole engine lifetime and mix earlier device/rate states. They must
not be used to judge the current stream. The per-ring `audio.timing` data
(512 most recent callbacks of the live stream) is the correct signal and it
is clean. This counter-reset behavior is a diagnostic defect to fix in a
separate, planned task.

## Conclusion
These captures do NOT show a sample-clock cause for the key drift. The ASIO
output is a clean, stable 48 kHz relative to the host clock, with no underflow
and no measurable DAC drift. The perceived key/pitch drift is not explained by
the ASIO sample rate or the DAC clock in this data.

## Remaining hypotheses (ranked)
1. The drift is slow/time-varying and the ~30 s observation window between
   dumps is too short to reveal a trend. A longer continuous capture is needed
   to see whether dac/host drifts away from 1.0 over minutes.
2. The pitch error is in the Focusrite hardware/DSP/monitoring path, not the
   ASIO sample clock. Note: PortAudio `dac_time` is a driver-internal sample
   counter; the host-measured callback cadence is the real hardware-rate
   measurement and it read exactly 48 kHz. A definitive, driver-independent
   check of the physical output pitch requires a physical loopback.
3. The perceived "drift" is actually a timing/LTC desync (transport position
   drifting vs the audio), not an audio pitch shift.

## Next step (per handoff; interface model now known = Scarlett 4i4)
Do the physical loopback test: play a known pure sine (e.g. 440.000 Hz) at
constant level, route Focusrite line-out -> line-in (or a second ASIO device),
record 30–60 s, and measure the output frequency over time (FFT / freq track).
This directly measures the physical output pitch and any drift, independent of
the driver counter. Do NOT apply any clock correction before this result.
Also capture a longer continuous run (5–10 min) with periodic report dumps to
rule out a slow dac/host trend.

## Files changed (this turn)
- .ai/REPORT.md (this analysis)
- .ai/handoffs/2026-09-06_FocusriteKeyDriftAnalysis.md
- .ai/NEXT_TASK.md (next step = physical loopback + long capture)

## Architecture decisions
Diagnosis only. No playback, clock, rate, routing, resample, or UI change.
AudioEngine remains the sole playback clock; driver timestamps are not
physical latency. All product constraints (Unicode, multi-version audio, one
output device, free channel routing, shared video clock, MA export rules)
remain intact.

## Tests performed
Parsed the three manual dumps' `audio.timing` rings and cross-dump spans with
analysis scripts in `.cache/` (`analyze_perf_rings.py`,
`cross_dump_drift.py`). Verified the music file native rate (48 kHz) via PyAV.
Verified counter-reset semantics by reading `AudioEngine.__init__` and
`_open_output_stream`. No runtime code executed; no production change.

## Remaining issues
- Key-drift root cause not yet confirmed; physical loopback and a longer
  continuous capture are still required before any clock decision.
- `Audio callback continuity` counters are cumulative since engine creation
  (only `_cb_last_mono`/`_cb_expected_period` reset per stream). This makes the
  `audio.callback.*` report section misleading for the current stream; a small
  planned fix (reset continuity counters on stream open) is recommended.
- No public clock change made.

## Suggested next task
Physical loopback pitch test on the Scarlett 4i4 (play 440.000 Hz sine, loop
line-out -> line-in, record 30–60 s, measure output frequency over time), plus
a 5–10 minute continuous playback capture with periodic report dumps to check
for a slow dac/host trend. Then, and only then, decide whether any clock
action is warranted. See docs/AUDIO_TIMING_DIAGNOSTICS.md and
docs/audit/2026-09-06/README.md.
