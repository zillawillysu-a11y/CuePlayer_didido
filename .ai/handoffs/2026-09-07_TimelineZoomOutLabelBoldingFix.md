# Timeline UI hardening: zoom-out label bolding (fixed-label render-order leak)

Date: 2026-09-07. Branch: `technical-audit-0815-028d`. Baseline: `c0bd6ca`. Status: complete.

## Task objective

The previous task fixed zoom-**in** label bolding (a `QPainter` font-state leak in
`_paint_zoom_screen_annotations`, plus explicit font resets in
`_paint_video_selection_live` / `_paint_ltc_selection_live`). Manual testing confirmed
zoom-in is fully fixed, but zoom-**out** still reproduces the same visible symptom:
Video / LTC Clips / Mark lane header labels temporarily render bold during a continuous
mouse-wheel zoom-out gesture, reverting to normal weight once the gesture stops.

This task's scope was limited to finding and fixing that remaining zoom-out-only defect,
without redoing the prior fix and without touching LTC domain/playback/MTC, the MA
exporter, persistence, AudioEngine, title-bar timecode, video sync, NDI, mark timing, or
selection semantics.

## Root cause

Zoom-in and zoom-out take different code paths through `_blit_zoom_preview`:

- The retained `_spatial_backdrop` raster is baked with an overscan margin sized around
  the *previous* PPS viewport.
- **Zoom-in** shrinks the visible time window, so it almost always stays inside that
  cached/overscanned region — the normal scaled-blit path runs, which calls
  `_paint_zoom_screen_annotations` (already save/restore-guarded by the prior fix).
- **Zoom-out** grows the visible time window, which exceeds the cached region's overscan
  bounds on nearly every wheel-out tick. This routes into the "exact viewport fallback"
  branch (`_blit_zoom_preview`, `outside_cache` branch), which calls
  `_paint_static_layers(painter)` directly and **returns without ever calling
  `_paint_zoom_screen_annotations`** — bypassing the font guard added for zoom-in
  entirely.

`_paint_static_layers` draws (in order): waveform → beat grids → video lane → LTC lane →
lanes → `_paint_marks(mode="static")` → splitters → `_paint_headers`. Inside
`_paint_marks_impl` (`timeline_widget.py`), the on-waveform Cue/Note caption for a mark
(drawn when a lane has `show_cue_id_on_wave` / `show_note_on_wave` enabled) sets the
shared painter's font to bold + a custom point size to draw the caption, and **never
restored it** — an independent, pre-existing font leak that the zoom-in fix never
touched because zoom-in rarely reaches this code path.

Because nothing resets the painter's font between that leak and `_paint_headers`, every
subsequent unguarded `drawText` for the rest of that bake — the "Video" label, "LTC
Clips" / "LTC L" / "LTC R" labels, and Mark lane name labels — inherits the leaked bold
weight. This reproduces on essentially every zoom-out wheel tick (because the fallback
path is taken nearly every time) and stops as soon as the gesture ends and normal
painting resumes, matching the reported symptom exactly.

Root cause classification (per the four hypotheses considered): **(D) a zoom-out-specific
compositing branch** (the exact-viewport fallback) that reaches an existing unguarded
bold-font mutation far more often than the zoom-in branch does. Not a rect-rounding/DPR
issue, not literal double-rendering of the same glyph, and not fixed-label geometry being
included in a scaled raster.

## Fix

- `timeline_widget.py`, `_paint_marks_impl`: wrapped the bold cue/note wave-label font
  mutation in `painter.save()` / `painter.restore()`, matching the pattern already used
  for `_paint_zoom_screen_annotations`'s Mark-glyph font. This closes the leak at its
  source for every caller of `_paint_marks`/`_paint_static_layers`, not just the
  zoom-out path.
- `timeline_widget.py`, `_paint_headers`: defense in depth — the function now explicitly
  `painter.setFont(self.font())` right after its own `painter.save()`, so it never
  depends on the ambient painter font state left by whatever ran before it in the same
  bake. This mirrors the same defensive pattern already used in
  `_paint_video_selection_live` / `_paint_ltc_selection_live`.

No rect/PPS/scaling math, blit compositing order, or renderer architecture was changed.

## Files changed

- `src/cueplayer/ui/timeline_widget.py` — `_paint_marks_impl` bold-font save/restore;
  `_paint_headers` explicit font reset at entry.
- `tests/ui/test_timeline_zoom_rendering_invariants.py` — added
  `test_static_layer_bake_does_not_leak_bold_font_into_headers`, a zoom-out-specific
  regression that calls `_paint_static_layers` directly (the exact function the zoom-out
  exact-viewport fallback calls) with a mark configured to show cue/note wave labels, and
  asserts the painter's font weight is unchanged afterward. The prior zoom-in regression
  (`test_zoom_screen_annotations_do_not_leak_bold_font`) was kept as-is.

## Tests performed

- `tests/ui/test_timeline_zoom_rendering_invariants.py` — 5 passed (new zoom-out
  regression + all previously existing zoom invariant tests).
- Broader targeted UI regression (39 test files covering timeline, LTC, Mark, zoom,
  setlist-LTC areas) — 144 passed.
- `tests/ui/test_timeline_scrub_backdrop_font.py::test_scrub_backdrop_uses_widget_font` —
  pre-existing failure (`TypeError: _capture() got an unexpected keyword argument
  'include_marks'`), confirmed present on baseline `c0bd6ca` before this change (verified
  via `git stash`), unrelated to this task, not touched.
- Excluded per task instructions: `test_cue_list_playhead_scroll.py`, the Windows
  video_sync crash test. Also excluded `test_timeline_video_track_controls.py` and
  `test_transport_main_window_center.py` from the broad run — both crash/hang due to a
  pre-existing, unrelated non-daemon background thread (`webrtc_listen`) not shutting
  down cleanly under the offscreen Qt test platform; not caused by or related to this
  change.
- `git diff --check` — clean.

## Manual verification steps for the user

1. Load a song with Video, LTC Clips (clip_generator), and at least one Mark lane
   visible.
2. Continuously zoom **out** with the mouse wheel over several seconds.
3. Confirm the "Video" / "LTC Clips" / Mark lane labels stay at normal font weight
   throughout the zoom-out gesture (previously they would visibly go bold).
4. Confirm zoom-in still behaves correctly (already fixed, should be unaffected).
5. Confirm marks with on-waveform Cue/Note captions enabled render normally (not bold)
   at rest and do not affect header label weight afterward.

## Remaining issues

None known for zoom-in or zoom-out label bolding. Pre-existing, unrelated issues noted
during this session (not touched, see `.ai/NEXT_TASK.md`):
`test_timeline_scrub_backdrop_font.py::test_scrub_backdrop_uses_widget_font` (pre-existing
`TypeError`, confirmed present on baseline before this change), and two UI test files
(`test_timeline_video_track_controls.py`, `test_transport_main_window_center.py`) that can
hang/crash the interpreter under the offscreen Qt platform due to a pre-existing
non-daemon `webrtc_listen` thread.

## Suggested next task

None queued — see `.ai/NEXT_TASK.md`. Await next manual-test findings.
