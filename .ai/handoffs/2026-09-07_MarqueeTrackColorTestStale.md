# Release Preflight blocker resolution: marquee-over-track-colors test was stale

Date: 2026-09-07. Branch: `technical-audit-0815-028d`. Baseline: `70611875fd52b516f86a55dfd0a4ae721b95607f`.

## Task objective

Release Build Preflight (previous session) surfaced one failing test as the sole
blocker: `tests/ui/test_marquee_over_track_colors.py::test_selection_box_paints_after_mark_track_colors`.
The user had already manually verified the marquee selection box paints correctly above
mark track colors, across Video/LTC/Mark, with group move, in the live app. This task's
job was to determine whether the failure was a real production regression or a stale test
assumption, and fix the correct side — without touching the already-verified cached
backdrop architecture unless a real bug was found.

## Finding: stale test, not a production regression

The old test asserted `TimelineWidget._paint_lanes` (the method that paints the
mark-track-color lane fills) must be called on every `paintEvent` while box-selecting,
then asserted `_paint_selection_box` runs after it.

That assumption predates the static backdrop cache serving box-select frames.
Reading `paintEvent`, `_blit_scrub_backdrop` / `_blit_native_backdrop`,
`_rebuild_scrub_backdrop`, and `_paint_lanes` shows the real paint order is:

```
_can_use_static_backdrop()  # always True — box-select does not disable the cache
  -> _blit_scrub_backdrop(painter)
       cache hit:  blit the retained native pixmap as-is (lanes already baked in)
       cache miss: _rebuild_scrub_backdrop() -> _paint_static_layers() -> ... -> _paint_lanes(...)
                   then blit the freshly-baked pixmap
  -> (dynamic overlays: waveform overlay, video/ltc selection, mark stems, marks,
      loop region, selected beat grid, beat-grid guide)
  -> _paint_selection_box(painter)   # always after the blit, either path
  -> audio loading overlay, playhead, gain overlays, drag guides, header splitter
```

`_paint_selection_box` is unconditionally called after `_blit_scrub_backdrop` returns
(success or not — see the non-cached fallback further down `paintEvent`, which calls
`_paint_static_layers` then the same overlay chain including `_paint_selection_box`).
So the box is always painted after the lane/track-color fills, whether or not
`_paint_lanes` happened to run *that specific frame*. Re-baking lanes on every
box-select tick would defeat the point of the static backdrop cache (the whole reason it
exists — see the Windows scrub/zoom performance notes in `timeline_widget.py`).

This is why the manual check was clean: the actual product invariant (box above track
colors) was never broken. Only the test's stricter, now-incorrect assumption (`_paint_lanes`
must run every frame) was wrong.

## What changed

- `tests/ui/test_marquee_over_track_colors.py` only. No production code touched.
- Old single test replaced with two, both spying on real paint helpers via method
  wrapping (no mocks of Qt internals, no pixel screenshots):
  - `test_selection_box_paints_after_mark_track_colors_fresh_bake` — invalidates the
    scrub backdrop first (`_invalidate_scrub_backdrop`), so the frame must rebuild;
    asserts `_paint_lanes` runs, then `_paint_selection_box`.
  - `test_selection_box_paints_after_mark_track_colors_cached_backdrop` — warms the
    cache with track colors already enabled, then box-selects and repaints; asserts the
    blit (`_blit_scrub_backdrop` returning a hit) runs, then `_paint_selection_box`, and
    that `_paint_lanes` need *not* run that frame.

Both tests lock the real invariant (overlay always paints after whichever background
path served that frame) under both cache states, instead of coupling to one internal
helper's call count.

## Verification

```
pytest tests/ui/test_marquee_over_track_colors.py tests/ui/test_marquee_group_move.py -q
# 11 passed

pytest tests/util/test_app_info.py tests/ui/test_about_dialog_and_title.py \
       tests/ui/test_splash.py tests/util/test_runtime.py tests/domain -q
# 181 passed
```

## Release Preflight status after this fix

- Production visual invariant: confirmed correct by code reading (matches user's manual
  verification).
- Stale test: updated to test the real invariant, not internal call frequency.
- Targeted tests: all green (see above).
- Git: working tree clean before/after, local branch pushed and equal to remote.

No other items from the previous Release Preflight report changed; see that report's
version/metadata/icon/build-script findings, which all passed and are unaffected by this
fix.
