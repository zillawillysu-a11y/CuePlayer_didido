# Next task

**Verify the MTC micro-regression re-anchor fix on Windows hardware/virtual MIDI.**

The supplied 2026-09-08 log showed the previous sender build issuing 408 false
backward full-frame re-anchors. The production fix now monotonic-clamps sample-clock
interpolation regressions within one transport generation while preserving real
backward seek/loop behavior. See `.ai/REPORT.md` and
`.ai/handoffs/2026-09-08_MtcMicroRegressionReanchorFix.md`.

Build/run this commit with `CUEPLAYER_PERF=1`. Play continuously for 30-60 seconds and
repeat the same stress sequence: dense Timeline wheel zoom and Video Track loading,
while observing an external MTC receiver. Capture a new receiver video and performance
report.

Acceptance criteria for a run with no intentional backward seek/loop:

- Audio output underflows remain zero.
- `mtc.qf_send_failures == 0`.
- QF throughput remains approximately 120/s at 30 fps.
- `mtc.overdue_reanchors == 0`.
- `mtc.backward_reanchors == 0`.
- `mtc.clock_regression_clamps` may be non-zero; those regressions should be absorbed
  and reported in `mtc.clock_regression_ms`, not converted to full-frame re-anchors.

If visible receiver stutter remains after all criteria pass, compare
`mtc.scheduler.wakeup_lateness_ms`, `mtc.tick_exec_ms`, `mtc.missed_qf`,
`mtc.catch_up_qf`, and `mtc.qf_due_max` before changing production behavior again.

Do not start Phase B/C, Ripple Edit, or another MTC redesign before this verification
is reviewed.
