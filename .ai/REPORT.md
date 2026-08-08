# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Fourth round of the same-day layout feedback:

1. Rename the table columns: "Chinese" → **Song**, "Song" → **Export Name**.
2. A song with no separate Chinese name (e.g. `88Bars`) must still show its
   name in the Song column — never a blank cell. Same in Review & Export.
3. **Manual Pool Starts was still broken after three fix attempts.** User
   suggested removing the explanatory text and spacing the rows evenly.

## What was implemented

### Manual Pool Starts — root cause finally identified and *proven*

The previous three attempts all failed because I kept rewriting the field
layout (grid → grid → QFormLayout) and verifying by inference rather than
measurement. This time I measured real rendered geometry offscreen and ran
a controlled single-variable experiment. Result:

| variant | row pitch | field height | overlaps |
|---|---|---|---|
| with word-wrapped hint label | 25px | 38px | **5 (13px each)** |
| without it | 49px | 41px | **0** |

**Root cause:** the `manual_hint` `QLabel` with `setWordWrap(True)` sitting
above the fields. A word-wrapped QLabel under-reports its height-for-width,
so the parent `QVBoxLayout` under-allocates, `QFormLayout` compresses the
row pitch to 25px, but each spinbox still paints at its stylesheet
`min-height: 32px` (38px with border/padding) — 13px of overlap per row.
The field layout was never the problem, which is why three rewrites of it
changed nothing.

I also verified, by the same method, that my other two speculative changes
(`setFixedWidth`, `setMinimumHeight(30)`) were **not** what fixed it —
removing the wrapped label is. They're kept only as cheap defense-in-depth.

Fix: removed the wrapped hint; its text now lives in a tooltip on the
group box, so no information is lost. Also gave `review_summary` (the other
wrapped label in that same column) an explicit minimum height so it can't
cause the same class of bug.

### Geometry regression guard

Because this bug survived three fixes purely because it was only ever
checked by eye, added `test_manual_pool_start_rows_never_overlap`,
parametrized over four window heights (900/700/560/440). It asserts real
rendered geometry: no row overlaps another, no spinbox crushed below 20px.
**Verified the guard actually works** — re-injecting the wrapped label makes
all four parametrizations fail; removing it makes them pass.

### Column renames and the blank-cell fix

- Both tables: `Order, Song, Export Name, …` (was `Order, Chinese, Song, …`).
- The Song column now shows `song.name or slot.display_name`, so a song
  named only in English (`88Bars`) shows `88Bars` instead of a blank cell.
  Still display-only — the exporter always uses Export Name.
- Added `test_song_column_falls_back_to_the_english_name_when_there_is_no_chinese`.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`

## Architecture decisions

Keep word-wrapped `QLabel`s out of narrow fixed-width control columns, or
give them an explicit minimum height. When a UI bug survives more than one
fix, stop inferring and measure the actual rendered geometry — and leave
behind an assertion on that geometry rather than a visual-only check.

## Tests performed

- `QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python.exe -m pytest tests/ui/test_show_patch_ma2_discovery.py tests/ui/test_setlist_folder_drag.py tests/exporters tests/persistence -q`: **199 passed**.
- Controlled single-variable experiment isolating the root cause (table above).
- Negative test of the new guard: reintroducing the bug fails all four
  parametrizations; restoring the fix passes them.
- `compileall`: passed.

## Remaining issues

- Manual Pool Starts is now verified by measurement rather than only by eye,
  but the user should still confirm it visually once, since offscreen
  rendering can differ from a real display in font metrics.
- Same outstanding manual-verification checklist as prior handoffs
  (`.ai/NEXT_TASK.md`): per-song Pool overrides, View Layout Follow
  checkbox, Setlist drag into Export Queue, and one real MA2 export.
- Pre-existing full `tests/ui` suite stack-overflow crash, unrelated.
- `startup_error.txt` and `.codex-test-tmp/` left untouched.

## Suggested next task

User confirms this round visually, then works through the remaining
manual-verification checklist in `.ai/NEXT_TASK.md` — most importantly the
real MA2 export with an active per-song Pool override.
