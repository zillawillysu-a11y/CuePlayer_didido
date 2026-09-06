# Next task

No new task queued yet. Candidates parked by user (not started):

- Physical loopback 440 Hz + long-capture drift check.
- Pre-existing unrelated failures documented in `.ai/REPORT.md` history (Windows video-sync
  access violation, NDI probe test, `test_song_use_left_ltc.py` routing assertions) — investigate
  only if the user asks; not blocking.
- `tests/ui/test_cue_list_playhead_scroll.py` hangs/crashes the interpreter on Windows when run
  as part of a full `tests/ui` sweep (pre-existing, unrelated to timeline zoom work) — investigate
  only if the user asks.

Both previously-parked manual re-checks are now resolved:

- Initial `clip_generator` LTC Clips lane hydration on project reopen (Problem A) — fixed by
  making `ShowSessionService.refresh_timeline()` push the resolved LTC mode synchronously.
- Track/lane header label "temporarily bold during zoom" artifact (Problem B) — root-caused to a
  leaked bold `QFont` on the shared zoom-preview `QPainter` and fixed with `save()`/`restore()` +
  explicit font resets in the two live-caption paint functions.

See `.ai/handoffs/2026-09-07_TimelineUiHardeningClipLaneAndZoomFontLeak.md` for the just-completed
task, and `.ai/handoffs/2026-09-06_TimelineZoomRenderingHardening.md` for the prior one.
