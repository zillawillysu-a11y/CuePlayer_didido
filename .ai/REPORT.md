# Timeline zoom rendering hardening: fix stretched LTC clip text + false mark selection ring

Date: 2026-09-06. Branch: `technical-audit-0815-028d`. Baseline: `b891e50`. Status: complete.

## Task objective

Fix three visual artifacts reported during manual testing of LTC Generator Clips, all
transient (appear only while the mouse wheel is actively zooming, and self-correct once
the wheel stops):

1. LTC clip text gets geometrically distorted (looks stretched/scaled) during zoom.
2. All Marks show a bright white outline during zoom, as if selected.
3. Track/lane header labels appear to go bold during zoom.

No domain/mapping, playback, MTC, exporter, persistence, AudioEngine, drag/trim, or
selection-semantics code was touched — this was a rendering-only investigation and fix.

## Root cause

The timeline widget is a custom-painted `QWidget` (no `QGraphicsView`/scene transform
scaling anywhere). During a wheel-zoom gesture it uses a raster preview optimization
(`_blit_zoom_preview`) that keeps a retained "spatial" `QPixmap` bake of static layers and
stretches it via `painter.drawPixmap(QRectF dest, pm, QRectF src)` to follow the live PPS
while the user is still turning the wheel, then idle-bakes a sharp cache once the gesture
settles. Anything that must stay pixel-crisp during that stretch (ruler timecodes, Mark
glyphs/notes) is deliberately excluded from the stretched raster and instead redrawn live,
at fixed size, every frame in `_paint_zoom_screen_annotations`.

Two concrete bugs broke that contract:

- **LTC clip rects/text were never excluded.** `_paint_static_layers` called
  `_paint_ltc_lane` → `_paint_ltc_clips` unconditionally, so the clip's rounded rect,
  border, and start-timecode text were baked straight into the same "spatial" pixmap as
  the waveform — and therefore got geometrically resampled by the same stretch that keeps
  the waveform following the wheel. That is bug 1's exact cause.

- **`_bake_mark_annotation_sprites` hardcoded a selection-style ring.** The live/normal
  marker paint (`_paint_marks`, used outside zoom) only draws a white outline when
  `ring = selected or hovered or dragging`. But the sprite baked specifically for the zoom
  preview called `draw_marker_shape(..., outline=QColor(255,255,255,210), outline_width=1.8)`
  unconditionally for every mark, regardless of its actual selection/hover state. Since
  these sprites are the *only* thing drawn for marker glyphs while `_blit_zoom_preview` is
  active, every mark looked selected for the duration of the gesture. That is bug 2's exact
  cause.

Bug 3 (label boldness) could not be reproduced from a corresponding code defect in this
audit: header/track-label text is confined to the `x < header_width` column, which
`_blit_zoom_preview` blits 1:1 (no stretch) in both the zoom-preview and native-cache
paths, and antialiasing is already disabled uniformly in both the live paint and the
bake — there is no code path where header text is drawn with a different weight or
transform during zoom. It is plausible this was a downstream visual artifact of bug 1/2
(a stretched/misaligned adjacent region reading as "heavier" text nearby) rather than an
independent defect; flagged below as the next manual-test item to re-check now that 1 and
2 are fixed.

**Are the three artifacts the same root cause?** Bugs 1 and 2 are the same *class* of
defect (fixed-size overlay content leaking into the raster that's allowed to be
geometrically resampled) but are two independent call sites, each fixed separately. Bug 3
was not isolated to a code defect.

## What was implemented

`src/cueplayer/ui/timeline_widget.py`:

- `_paint_static_layers(...)` gained an `include_ltc_clips: bool = True` parameter,
  threaded into `_paint_ltc_lane(..., include_clips=...)`, which now skips
  `_paint_ltc_clips` when `include_clips=False`.
- `_rebuild_scrub_backdrop`'s spatial bake now passes `include_ltc_clips=False` — LTC clip
  geometry/text is no longer part of the stretchable raster.
- Its full bake (used for scrub/play at matching PPS, blitted 1:1) explicitly calls
  `_paint_ltc_clips(fp)` again after copying the spatial pixmap, so that path is unaffected.
- `_paint_zoom_screen_annotations` (the fixed-size-overlay repaint run every zoom-preview
  frame) now also calls `_paint_ltc_clips(painter)` live, at current geometry/PPS — mirroring
  how Marks and ruler labels already worked. Clip rects/text now track zoom purely through
  their coordinate math (`_x_for_time`), never through pixmap resampling.
- `_bake_mark_annotation_sprites` now computes each mark's actual `selected`
  (`mark.id in self._selected_mark_ids`) and `hovered` (`mark.id == self._hover_mark_id`)
  state and only passes an outline when `ring = selected or hovered`, matching the live
  paint's alpha/width scheme (`230/2.2` selected, `210/2.0` hovered, no outline otherwise).
  It also now scales marker `size` up for a selected mark (`0.36` vs `0.28` of lane height),
  matching the live-paint proportions.

No changes to LTC clip domain/mapping, playback, MTC, exporters, persistence, AudioEngine,
mark timing math, selection semantics, drag/trim semantics, video sync, or NDI.

## Files changed

- `src/cueplayer/ui/timeline_widget.py`
- `tests/ui/test_timeline_zoom_rendering_invariants.py` (new)
- `.ai/REPORT.md`, `.ai/handoffs/2026-09-06_TimelineZoomRenderingHardening.md`, `.ai/NEXT_TASK.md`

## Tests performed

New file `tests/ui/test_timeline_zoom_rendering_invariants.py` (3 tests, all pass):

- `test_spatial_backdrop_excludes_ltc_clip_rects` — proves `include_ltc_clips=False` has an
  observable effect on the spatial-layer render (i.e. the exclusion flag actually works, so
  the stretchable raster genuinely omits clip geometry).
- `test_zoom_preview_repaints_ltc_clips_live` — spies on `_paint_ltc_clips` and asserts
  `_paint_zoom_screen_annotations` calls it every frame (proves clips are redrawn live
  during zoom, not resampled from a cached bitmap).
- `test_mark_annotation_sprite_outline_matches_selection_state` — bakes sprites with no
  selection, asserts no sprite pixmap contains near-white/high-alpha pixels (no false
  selection ring), then selects one mark and asserts only that mark's sprite carries the
  ring.

These are flag/state/behavior invariants (no pixel-perfect screenshot comparisons), per the
task's guidance to avoid fragile screenshot tests without an existing fixture harness.

Ran and passed (52 existing + 3 new = 55):
`tests/ui/test_ltc_clip_timeline.py`, `test_timeline_zoom_overlay_resize.py`,
`test_timeline_keep_zoom.py`, `test_zoom_waveform_geometry.py`, `test_zoom_cue_video_state.py`,
`test_scrub_render_parity.py`, `test_play_pause_static_parity.py`,
`test_timeline_pan_no_flash.py`, `test_timeline_overview.py`,
`test_timeline_zoom_rendering_invariants.py`.

Not run: a full `tests/ui` sweep was attempted but `test_cue_list_playhead_scroll.py`
hangs/crashes the interpreter on this Windows box (pre-existing, unrelated to this change —
matches the task's "known-crashing unrelated Windows tests" caveat); the full-directory run
was killed after ~10 minutes with no output and not retried. The relevant/targeted subset
above is the regression evidence for this change.

## Next suggested manual test

1. Re-verify LTC clip text no longer distorts during continuous wheel zoom (should now be
   crisp throughout).
2. Re-verify Marks no longer show a white "selected-looking" outline during zoom unless
   actually selected/hovered.
3. Re-check the track/lane header label "temporarily bold" observation with 1 and 2 fixed —
   if it persists, it's an independent defect needing its own repro/audit.
