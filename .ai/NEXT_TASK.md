# Next task

No new task queued yet. Candidates parked by user (not started):

- Physical loopback 440 Hz + long-capture drift check.
- Pre-existing unrelated failures documented in `.ai/REPORT.md` history (Windows video-sync
  access violation, NDI probe test, `test_song_use_left_ltc.py` routing assertions) — investigate
  only if the user asks; not blocking.
- `tests/ui/test_cue_list_playhead_scroll.py` hangs/crashes the interpreter on Windows when run
  as part of a full `tests/ui` sweep (pre-existing, unrelated to timeline zoom work) — investigate
  only if the user asks.
- `tests/ui/test_timeline_scrub_backdrop_font.py::test_scrub_backdrop_uses_widget_font` fails on a
  pre-existing `TypeError` (test double doesn't accept `include_marks` kwarg added to
  `_paint_static_layers` by a prior task) — confirmed present on baseline `c0bd6ca` before today's
  change, not caused by it; investigate only if the user asks.
- `tests/ui/test_timeline_video_track_controls.py` and `test_transport_main_window_center.py` can
  crash/hang the interpreter under the offscreen Qt test platform due to a pre-existing, unrelated
  non-daemon `webrtc_listen` background thread not shutting down cleanly — investigate only if the
  user asks.

Resolved this session:

- Zoom-**out** track/lane header labels ("Video" / "LTC Clips" / Mark lane names) temporarily
  going bold during a continuous wheel-zoom-out gesture (the zoom-in case was already fixed in the
  prior task) — root-caused to an unguarded bold-font mutation in `_paint_marks_impl`'s on-waveform
  Cue/Note caption, reached almost every zoom-out tick via `_blit_zoom_preview`'s exact-viewport
  fallback (`_paint_static_layers`), which bypasses the zoom-in fix's `_paint_zoom_screen_annotations`
  guard entirely. Fixed with `save()`/`restore()` around that font mutation plus a defensive font
  reset at the top of `_paint_headers`.

Previously resolved (`758068a` → `c0bd6ca`):

- Initial `clip_generator` LTC Clips lane hydration on project reopen — fixed by making
  `ShowSessionService.refresh_timeline()` push the resolved LTC mode synchronously.
- Zoom-**in** track/lane header label bolding — root-caused to a leaked bold `QFont` on the shared
  zoom-preview `QPainter` in `_paint_zoom_screen_annotations`, fixed with `save()`/`restore()` +
  explicit font resets in `_paint_video_selection_live` / `_paint_ltc_selection_live`.

See `.ai/handoffs/2026-09-07_TimelineZoomOutLabelBoldingFix.md` for the just-completed task,
`.ai/handoffs/2026-09-07_TimelineUiHardeningClipLaneAndZoomFontLeak.md` for the zoom-in +
clip-lane-hydration task, and `.ai/handoffs/2026-09-06_TimelineZoomRenderingHardening.md` for the
one before that.
