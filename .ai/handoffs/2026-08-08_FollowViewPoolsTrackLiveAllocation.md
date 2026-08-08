# Follow Console Setup View Pools Track the Live Allocation

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

With "Follow Console Setup" ticked, the View Layout numbers did not move when
the user changed numbers on the Export page — via a manual per-song edit,
Auto-Fill, or Start after scanned Pools.

## What was implemented

Two separate causes, both confirmed by reading the call order first:

1. **It followed the wrong source.** `_console_pool_start_stride()` read the
   Console Setup spinboxes (`seq_start`, `ma2_effect_pool_start`, …). But
   manual per-song edits, Auto-Fill and Start-after-scanned all change the
   *allocated* numbers in `self._slots`, not those spinboxes — so the View
   had nothing to react to.
2. **It ran too early.** `_sync_following_view_pools()` was called from
   `_write_ui_to_settings()`, which runs at the *top* of `refresh()` — before
   `build_show_patch()` rebuilds `self._slots`. Even after fixing (1) it
   would have used the previous cycle's allocation.

Fixes:

- `_console_pool_start_stride()` now derives from `self._slots`: `start` is
  the first song's real value for that Pool, and `stride` is the actual gap
  between the first two songs (so an Auto-Fill with its own spacing is
  reflected exactly), falling back to the Console Setup fields when no songs
  are queued.
- The sync moved into `refresh()` *after* `build_show_patch()`, and now
  returns whether anything moved so the layout is persisted to
  `ma2_view_layout` only when it actually changed.

Unticking Follow still releases the Pool to its own independent number.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`

## Architecture decisions

"Follow" now means "track the effective allocation", not "mirror one
spinbox" — the View Layout preview shows the numbers that will actually be
exported, whatever changed them.

## Tests performed

- Targeted suites: **130 passed**.
- New `test_following_view_pool_tracks_the_live_allocation_not_just_console_setup`
  walks all four cases: Start after scanned Pools (509), Auto-Fill (100),
  manual per-song edit (640), and that unticking Follow pins it at 42 while
  later edits are ignored.

## Remaining issues

- The exported Song View still computes each song's number as
  `start + song_index * stride`, so a View following an *irregular* set of
  manual per-song pins is exact for the first song and evenly spaced after
  it. Regular cases (Auto-Fill, Start-after-scanned, plain allocation) are
  exact. Worth revisiting only if per-song irregular View numbers are needed.
- 11 pre-existing `tests/ui/test_setlist_*` failures, verified unrelated.

## Suggested next task

User confirms the View Layout numbers now track the Export page, then the
outstanding item is one real MA2 export.
