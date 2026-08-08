# Page Width Overflow (Group fields unreachable) + Blank Pool Seeds

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

User reported: (1) every Group-related field in Console Setup had become
impossible to fill in; (2) Manual Pool Starts still looked wrong — tall with
overlapping rows after Clear All Overrides, shrunken after Auto-Fill; (3)
they want to be able to leave a seed field blank so that filling only
Timecode renumbers just the Timecode column.

## What was implemented

### 1. Group fields "not editable" — actually a page-width overflow

Measured rather than guessed. The Group widgets were `enabled=True`,
`readOnly=False`, and `setValue()` worked — so it was never an input-state
problem. The real cause: the page's **minimum width was 2824px**, so
`resize(1600)` could not take effect and the Pool Start fields rendered at
x≈1510–2185, i.e. outside any normal window, with no scrollbar. They were
literally off-screen, not disabled.

Two labels drove that minimum:

- `out_hint` (Output Folder hint) — one long line demanding **1620px**,
  forcing `setup_page` to 2796px.
- `ma2_detect_status` — the "Running … · Installed 3.1.2, 3.3.4, …" line
  demanding **816px**, forcing the Console box to 1400px.

Both are now word-wrapped with sane width/height bounds; `ma2_version` is
capped (it holds "3.9.63.6", it was reserving 348px); the Pool Start
spinboxes are capped at 110px instead of expanding to ~270px each.

Minimum width went **2824 → 1785**. Because 1785 still exceeds a ~1650px
window, every workflow tab is now hosted in a `QScrollArea`
(`widgetResizable`, no frame), so an oversized page scrolls instead of
clipping controls out of reach. Final page minimum width: **464px**, with
every Pool Start field verified reachable at 1100/1280/1366/1600/1920.

### 2. Manual Pool Starts stability

`manual_box` now has a Fixed vertical size policy and the seed spinboxes a
fixed height, so a sibling that grows (the wrapped summary label gets longer
after a scan/Auto-Fill) can no longer squeeze the rows. Verified by
measuring geometry across initial → Clear All Overrides → Auto-Fill →
scan-text-grows: 0 overlaps in every state.

### 3. Blank seeds mean "leave this Pool alone"

- Seed fields are now range 0–9999 with `specialValueText`, so 0 renders
  blank, and they start blank.
- `_rebuild_workflow_pages` no longer rewrites them from Console Setup on
  every refresh — that overwrite was why a deliberately blank field could
  never stick.
- `_auto_fill_pool_overrides` skips blank Pools entirely, and reports it
  when every seed is blank instead of silently doing nothing.

### 4. Precedence between the two bulk actions (follow-up in same session)

User then asked that Auto-Fill outrank "Start after scanned Pools", that the
toggle also appear on the Export page, and that a manually edited number not
snap back when the toggle is switched off. Resolved by making the precedence
explicit instead of having two bulk rules fight over the same numbers:

- Per-song pins now always win in `build_show_patch`, in either toggle state
  (previously the toggle ignored them). That is what makes a manual edit
  made while the toggle is on survive switching it off.
- Ticking the toggle clears pre-existing pins once, so it still visibly
  repositions everything, and says how many it cleared rather than dropping
  them silently.
- Auto-Fill switches the toggle off, so its numbers are used exactly as
  entered.
- The checkbox is mirrored on Review & Export; both copies stay in sync via
  `_sync_start_after_scanned_checkboxes`.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `src/cueplayer/exporters/show_patch.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `tests/exporters/test_show_patch.py`

## Architecture decisions

Long single-line `QLabel`s inside fixed-width panels must be word-wrapped or
they dictate the whole page's minimum width. Tab pages are scrollable by
default so no control can ever become unreachable on a smaller display.

## Tests performed

- Targeted suites: **129 passed** (new tests for blank-seed behaviour, the
  mirrored checkbox, manual-edit survival, Auto-Fill winning, and pin
  clearing; three existing tests updated for the intended contract changes —
  seeds now start blank, tabs host a `QScrollArea`, and ticking the toggle
  clears pins).
- Geometry measured directly: page min width 2824 → 464; all Pool Start
  fields reachable at five window widths; Manual Pool Starts 0 overlaps
  across four UI state changes.

## Remaining issues

- `setup_page` still has a ~1757px natural width; it now scrolls rather than
  clipping. Reflowing that row into two rows would remove the scrollbar on
  small screens, but was out of scope here.
- Groups overrides remain planning/report-only in the exporter (unchanged).

## Suggested next task

User confirms in the desktop app: Group fields in Console Setup accept input
again; Manual Pool Starts renders cleanly in all states; leaving all seeds
blank except Timecode renumbers only the Timecode column; the Start after
scanned Pools checkbox appears on both pages and stays in sync; a manually
typed number survives switching that toggle off; and Auto-Fill switches the
toggle off. Then one real MA2 export.
