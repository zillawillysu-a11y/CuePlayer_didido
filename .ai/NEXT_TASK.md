# Next task

**MTC sender production verification (manual Windows hardware/virtual-port run).**

The 2026-09-08 MTC sender starvation fix is implemented and automated tests are green;
see `.ai/REPORT.md` and
`.ai/handoffs/2026-09-08_MtcSenderStarvationFix.md`. Do not start another feature/fix
phase until this build is verified against a real WinMM MIDI receiver.

Run CuePlayer with `CUEPLAYER_PERF=1`, play continuously for 30–60 seconds while doing
the same stress sequence that reproduced the drop: dense Timeline wheel zoom + Mark
creation with Video Track loaded. Observe MTC in a MIDI monitor, write a performance
report, and return these two sections:

- `MTC sender continuity`
- `Audio callback continuity`

Follow-up order if a gap remains:

1. `mtc.qf_send_failures > 0` → MIDI backend/device path.
2. High `mtc.scheduler.wakeup_lateness_ms` with low `mtc.tick_exec_ms` → OS/GIL sender
   starvation.
3. High `mtc.tick_exec_ms` → compare `mtc.file_ltc_sync_ms`, `mtc.qf_dispatch_ms`, and
   `mtc.cue_dispatch_ms`; address only the dominant phase.
4. High `mtc.clock_snapshot_age_ms` plus audio callback deadline misses → sample-clock
   publisher/audio callback delay.
5. `mtc.qf_due_max > 8` or `mtc.overdue_reanchors > 0` → receiver-relevant long gap.

Do not start Phase B/C or Ripple Edit before this verification is reviewed.
