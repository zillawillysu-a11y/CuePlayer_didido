# Manual Pool Starts Root Cause (Proven) + Song/Export Name Column Rename

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Fourth round of same-day layout feedback: rename "Chinese"/"Song" columns to
"Song"/"Export Name"; never leave the Song cell blank for English-only song
names (88Bars); and fix Manual Pool Starts, which was **still** broken after
three attempts.

## What was implemented

### Manual Pool Starts — root cause found by measurement, not inference

Three prior attempts rewrote the *field layout* (grid → grid → QFormLayout)
and were verified by eye. All failed. This time the rendered geometry was
measured offscreen and a controlled single-variable experiment run:

| variant | row pitch | field height | overlaps |
|---|---|---|---|
| with word-wrapped hint label | 25px | 38px | **5 (13px each)** |
| without it | 49px | 41px | **0** |

**Root cause:** the `manual_hint` `QLabel` with `setWordWrap(True)` above the
fields. Wrapped QLabels under-report height-for-width → parent
under-allocates → `QFormLayout` compresses row pitch to 25px while each
spinbox still paints at its stylesheet `min-height: 32px` (38px with
border/padding) → 13px overlap per row. The field layout was never the
problem.

Also confirmed by the same method that `setFixedWidth` /
`setMinimumHeight(30)` were *not* the fix (kept only as cheap
defense-in-depth). Hint text moved to a tooltip on the group box so nothing
is lost. `review_summary` (the other wrapped label in that column) got an
explicit minimum height to prevent the same class of bug.

### Geometry regression guard

`test_manual_pool_start_rows_never_overlap`, parametrized over window
heights 900/700/560/440, asserts real rendered geometry (no overlap, no
crushed rows). **Negative-tested**: reintroducing the wrapped label fails all
four; removing it passes all four.

### Column rename + blank-cell fix

- Both tables now read `Order, Song, Export Name, …`.
- Song column shows `song.name or slot.display_name`, so `88Bars` shows
  `88Bars` rather than a blank cell. Display-only; the exporter still always
  uses Export Name.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`

## Architecture decisions

Keep word-wrapped `QLabel`s out of narrow fixed-width control columns (or
give them an explicit minimum height). When a UI bug survives more than one
fix, measure the rendered geometry instead of inferring, and leave an
assertion on that geometry behind.

## Tests performed

- Targeted suites (`show_patch_ma2_discovery`, `setlist_folder_drag`,
  `exporters`, `persistence`): **199 passed**.
- Controlled root-cause experiment (table above).
- Negative test proving the new guard actually catches the bug.
- `compileall`: passed.

## Remaining issues

Manual Pool Starts is now machine-verified, but offscreen font metrics can
differ from a real display — worth one visual confirmation. Rest of the
manual-verification checklist unchanged; see `.ai/NEXT_TASK.md`.

## Suggested next task

User confirms visually, then proceeds to the remaining checklist items —
especially a real MA2 export with an active per-song Pool override.
