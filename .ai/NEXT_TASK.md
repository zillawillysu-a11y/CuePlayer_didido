# Next task

No new task queued yet. Candidates parked by user (not started):

- Physical loopback 440 Hz + long-capture drift check.
- Pre-existing unrelated failures documented in `.ai/REPORT.md` (Windows video-sync access
  violation, NDI probe test, `test_song_use_left_ltc.py` routing assertions) — investigate only if
  the user asks; not blocking.
- `tests/ui/test_cue_list_playhead_scroll.py` hangs/crashes the interpreter on Windows when run
  as part of a full `tests/ui` sweep (pre-existing, unrelated to timeline zoom work) — investigate
  only if the user asks.
- Manual re-check: track/lane header label "temporarily bold during zoom" artifact — audited in
  the zoom-rendering-hardening task but not isolated to a code defect; re-verify whether it still
  reproduces now that the LTC clip text stretch and Mark false-selection-outline bugs are fixed.

See `.ai/handoffs/2026-09-06_TimelineZoomRenderingHardening.md` for the just-completed timeline
zoom rendering hardening task.
