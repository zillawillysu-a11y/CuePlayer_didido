# MTC Micro-Regression Re-anchor Fix

Date: 2026-09-08. Branch: `cursor/technical-audit-0815-028d`.

## Task objective

Diagnose the worse external-MTC stutter seen after the sender starvation fix by
reviewing the supplied screen recording and `cueplayer_perf.log`, then apply the
smallest production fix without reducing the 120 QF/s cadence, changing the audio
buffer, or returning MTC scheduling to a GUI `QTimer`.

## What was implemented

### Diagnosis from the supplied run

The latest complete performance dump in the supplied log belongs to the same app
session but precedes the 3.9-second screen recording, so it is session evidence rather
than an exact recording-window measurement. It nevertheless isolates the failure:

- DirectSound remained healthy: 7,213 callbacks, zero output underflows, and no MTC
  send failures.
- The lock-free clock read worked: `mtc.clock_read_ms` mean 0.005 ms, max 0.122 ms.
- Scheduler/tick delays existed but were bounded in this dump: wake lateness max
  7.457 ms, QF dispatch max 5.353 ms, and tick execution max 5.387 ms.
- QF recovery was active: 541 missed QFs were recovered over 502 catch-up wakeups;
  `mtc.qf_due_max` reached 6 and `mtc.overdue_reanchors` remained zero.
- The decisive anomaly was `mtc.backward_reanchors == 408`. The sample-clock
  extrapolator can advance slightly beyond the next audio callback's exact write-head
  when that callback arrives earlier than its nominal block period. `MtcOutput`
  interpreted each small interpolation regression as a real backward seek and sent a
  full-frame SysEx re-anchor, repeatedly breaking QF continuity. The absolute 4 ms
  scheduler observes this condition more often, explaining why the previous build
  could appear worse externally even though audio remained clean.
- Video decode submissions correlate with CPU/GIL load but do not hold the
  `AudioEngine` clock lock. They are a stressor, not the primary cause found here.

### Minimal production fix

- Added a monotonic floor to the lock-free MTC clock view, scoped to one transport
  generation. Small callback/interpolation regressions are clamped instead of being
  passed to `MtcOutput` as backward discontinuities.
- Included the transport generation in the immutable clock snapshot. Real seek, loop,
  and playback-rate discontinuities increment the generation and therefore remain
  allowed to move the clock backward.
- Reset the MTC floor whenever the sender thread starts, preventing stale state from a
  previous run.
- Added `mtc.clock_regression_ms` and `mtc.clock_regression_clamps` diagnostics. A
  non-zero clamp count is expected evidence that jitter was absorbed; it must no
  longer correlate with `mtc.backward_reanchors`.
- Kept the existing absolute-deadline 4 ms sender loop and sample-clock QF catch-up.
  No QF rate, audio buffer, MIDI backend, video pipeline, or GUI timer was changed.

## Files changed

- `src/cueplayer/playback/audio_engine.py`
- `src/cueplayer/diagnostics/perf.py`
- `tests/playback/test_mtc_gui_stall_independence.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-09-08_MtcMicroRegressionReanchorFix.md`
- `.ai/NEXT_TASK.md`

## Architecture decisions

- `AudioEngine._position_frame` remains the only playback clock. The monotonic floor
  is an MTC-reader presentation guard, not a second clock.
- Discontinuity authority remains explicit through the existing transport generation;
  the clamp never hides a real engine seek/loop/rate transition.
- The audio callback stays the sole clock-snapshot writer, while the MTC sender remains
  an off-GUI dedicated thread and a lock-free reader.
- The fix is deliberately local to clock publication/consumption and does not move
  code across UI, Domain, Playback Engine, Media, Exporters, or Persistence boundaries.

## Tests performed

- Targeted MTC/LTC regression set: **47 passed**.
- Broad playback regression set excluding the three known environment/baseline files
  (`test_video_sync.py`, `test_ndi_probe.py`, `test_song_use_left_ltc.py`):
  **274 passed**.
- New regression coverage proves both sides of the rule: an early-callback 5 ms
  interpolation regression is clamped without SysEx, while a new transport generation
  accepts a real backward seek.

## Remaining issues

- The fix still needs a Windows hardware/virtual-MIDI receiver run using the same
  Timeline Zoom + Video Track load sequence.
- During a run without intentional backward seek/loop, the key acceptance criterion is
  `mtc.backward_reanchors == 0`; `mtc.clock_regression_clamps > 0` is acceptable and
  shows that the new guard is doing work.
- If receiver stutter remains with zero backward/overdue re-anchors and zero send
  failures, the next evidence to compare is wake lateness versus tick execution and QF
  debt, not the already-cleared audio callback or clock-lock hypotheses.

## Suggested next task

Build/run this commit on Windows with `CUEPLAYER_PERF=1`, play for 30-60 seconds while
repeating dense Timeline Zoom and Video Track loading, and capture a new performance
report plus receiver video. Confirm zero audio underflows/send failures, approximately
120 QF/s, `mtc.overdue_reanchors == 0`, and `mtc.backward_reanchors == 0` when no
intentional backward discontinuity occurs. Review that evidence before any further
MTC change or feature work.
