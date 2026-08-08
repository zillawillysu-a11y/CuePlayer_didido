# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

User reported three problems, then added three follow-up requirements, then
one final one:

1. Every Group-related field in Console Setup had become impossible to fill.
2. Manual Pool Starts still rendered wrong (tall with overlapping rows after
   Clear All Overrides, shrunken after Auto-Fill).
3. Seed fields should be blankable, so filling only Timecode renumbers just
   the Timecode column.
4. Auto-Fill must outrank "Start after scanned Pools" and switch it off.
5. That toggle must also be on the Export page.
6. A manually typed number must not snap back when the toggle is switched off.
7. With "Follow Console Setup" ticked, the View Layout numbers did not move
   when any of those Export-page changes were made.

## What was implemented

### Group fields "not editable" — really a page-width overflow

Measured instead of guessing: the widgets were `enabled=True`,
`readOnly=False`, and `setValue()` worked, so it was never an input-state
problem. The page's **minimum width was 2824px**, so `resize(1600)` could not
take effect and the Pool Start fields rendered at x≈1510–2185 — outside any
normal window, with no scrollbar. Two long single-line labels caused it:
`out_hint` demanded 1620px and `ma2_detect_status` 816px. Both are now
word-wrapped with bounds, `ma2_version` is capped (it holds "3.9.63.6" but
reserved 348px), and the Pool Start spinboxes are capped at 110px instead of
expanding to ~270px each. That took the minimum to 1785px; since that still
exceeds a ~1650px window, every workflow tab is now hosted in a
`QScrollArea`, so an oversized page scrolls instead of clipping controls out
of reach. Final page minimum width: **464px**, verified reachable at
1100/1280/1366/1600/1920.

### Manual Pool Starts stability

`manual_box` has a Fixed vertical size policy and the seed spinboxes a fixed
height, so a sibling that grows (the wrapped summary label after a scan or
Auto-Fill) can no longer squeeze the rows. Geometry measured across initial →
Clear All Overrides → Auto-Fill → scan-text-grows: 0 overlaps in every state.

### Blank seeds

Seeds are range 0–9999 with `specialValueText`, so 0 renders blank, and they
start blank. `_rebuild_workflow_pages` no longer rewrites them from Console
Setup every refresh — that overwrite was why a deliberately blank field could
never stick. `_auto_fill_pool_overrides` skips blank Pools and reports it when
every seed is blank instead of silently doing nothing.

### Precedence between the two bulk actions

The toggle and Auto-Fill were two bulk rules fighting over the same numbers.
Made the precedence explicit:

- Per-song pins now always win in `build_show_patch`, in either toggle state
  (previously the toggle ignored them) — this is what lets a manual edit made
  while the toggle is on survive switching it off.
- Ticking the toggle clears pre-existing pins once, so it still visibly
  repositions everything, and reports how many it cleared rather than
  dropping them silently.
- Auto-Fill switches the toggle off so its numbers are used exactly as typed.
- The checkbox is mirrored on Review & Export, both copies kept in sync by
  `_sync_start_after_scanned_checkboxes`.

### View Layout "Follow" tracked the wrong thing, at the wrong time

Two causes, both found by reading the call order first.
`_console_pool_start_stride()` read the Console Setup spinboxes, but manual
edits / Auto-Fill / Start-after-scanned change the *allocated* numbers in
`self._slots`, not those spinboxes. And `_sync_following_view_pools()` ran
from `_write_ui_to_settings()` at the top of `refresh()` — before
`build_show_patch()` rebuilt the slots — so even a corrected source would
have read the previous cycle.

Now the sync derives `start` from the first song's real value and `stride`
from the actual gap between the first two songs (so an Auto-Fill with its own
spacing is exact), and runs after `build_show_patch()`, persisting the layout
only when something moved. Unticking Follow still releases the Pool.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `src/cueplayer/exporters/show_patch.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `tests/exporters/test_show_patch.py`

## Architecture decisions

Long single-line `QLabel`s inside fixed-width panels must be word-wrapped or
they dictate the whole page's minimum width. Tab pages are scrollable by
default so no control can become unreachable on a smaller display. Where two
bulk actions can set the same value, one must explicitly win rather than
silently masking the other.

## Tests performed

- Targeted suites: **130 passed**. New tests cover blank-seed behaviour, the
  mirrored checkbox, manual-edit survival across the toggle, Auto-Fill
  winning, pin clearing, and a following View Pool tracking all three
  Export-page changes. Three existing tests were updated for the
  intended contract changes (seeds start blank, tabs host a `QScrollArea`,
  ticking the toggle clears pins).
- Geometry measured directly: page min width 2824 → 464; all Pool Start
  fields reachable at five widths; Manual Pool Starts 0 overlaps across four
  UI states.

## Remaining issues

- 11 pre-existing failures in `tests/ui/test_setlist_*` (sort, renumber,
  sheet_page, folder_actions, ltc_indicator). **Verified pre-existing** by
  stashing this diff and re-running — they fail identically without it, and
  none of those files are touched here. Same family as the known
  `tests/ui` full-suite instability.
- `setup_page` still has a ~1757px natural width; it now scrolls rather than
  clipping. Reflowing that row into two rows would remove the scrollbar on
  small screens but was out of scope.
- Groups overrides remain planning/report-only in the exporter (unchanged).
- The exported Song View computes each song's number as
  `start + song_index * stride`, so a following View is exact for regular
  allocations (Auto-Fill, Start-after-scanned, plain) and exact for the first
  song then evenly spaced under an irregular set of manual pins.

## Suggested next task

User confirms in the desktop app: Group fields accept input again; Manual
Pool Starts renders cleanly; blank seeds renumber only the filled Pool; the
toggle appears on both pages and stays in sync; a typed number survives
switching it off; Auto-Fill switches it off. Then one real MA2 export.
