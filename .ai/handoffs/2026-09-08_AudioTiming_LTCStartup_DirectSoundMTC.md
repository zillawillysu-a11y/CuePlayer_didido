# Audio Timing Reliability — LTC Startup + DirectSound/MTC

This handoff is the durable copy of `.ai/REPORT.md` for the 2026-09-08 phase. Read `.ai/REPORT.md` for the full evidence, lifecycle, benchmark, architecture decisions, test results, and remaining hardware A/B matrix.

## Task objective

Investigate Problem A (LTC Enable transient ~6 s stutter) and Problem B (DirectSound + MTC continuous severe stutter) independently; fix only evidence-backed causes.

## What was implemented

- Problem A status: **Strong evidence but not yet proven on post-fix hardware**. Real dump: 15 clips × 404.33 ms mean ≈ 6.06 s; two builder jobs were 6.02–6.14 s. Replaced scalar per-frame/per-bit LTC PCM rendering with bounded NumPy/native batches. 15×270 s benchmark: 6.0947 s → 0.9036 s; byte-exact equivalence.
- Added `audio.ltc_clip.builder_event_ring` for Enable/job/per-clip/completion timestamp correlation with callback counters.
- Problem B status: **Not reproduced / insufficient evidence**. Added stream config, variable frame-count, frame-derived period, interval-miss vs exec-over-budget, callback lock-wait, MTC loop/clock-lock/send metrics. No speculative B production fix.
- Proved MTC reads the callback-wide AudioEngine lock briefly but releases it before MIDI send; interleaved MTC does not alter variable-frame audio cursor.

## Files changed

See `.ai/REPORT.md`; production files are `timecode/ltc.py`, `playback/audio_engine.py`, and `playback/mtc_output.py`, with focused tests.

## Architecture decisions

AudioEngine remains the sole playback clock. LTC generation stays off callback. No Timeline/UI/export/persistence changes. Problem B remains instrumentation-only pending hardware evidence.

## Tests performed

- Focused audio/LTC/MTC: 114 passed.
- Broader non-video batch: 276 passed / 3 unrelated known/environment failures.
- Unfiltered playback sweep hit known Windows PyAV/video-sync native access violation and did not complete.
- Byte-exact scalar/vector LTC equivalence includes 24/25/30/29.97, DF flag, short/non-integer durations, midnight and batch boundary.

## Remaining issues

- Run Problem A post-fix hardware A1/A2/A3.
- Run Problem B ASIO/DirectSound × MTC OFF/ON matrix and identify B4-only degradation before any fix.
- Full-track stale LTC future cancellation remains lifecycle debt, now much cheaper after vectorization.

## Suggested next task

Execute `.ai/NEXT_TASK.md` hardware PERF matrix with the new metrics; confirm A, isolate B, then implement only the evidence-selected narrow B fix.
