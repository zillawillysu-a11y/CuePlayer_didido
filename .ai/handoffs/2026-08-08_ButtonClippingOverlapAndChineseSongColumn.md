# Button Clipping, Manual Pool Starts Overlap (Real Fix), Chinese Song Columns

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Follow-up on the same-day layout-width fix: Telnet action buttons got their
labels clipped after narrowing the box; Manual Pool Starts still overlapped
despite the earlier spacing fix; user wants Chinese names shown in the
Export Registry and Review & Export Song columns too.

## What was implemented

- **Telnet buttons**: split the packed status+4-buttons row into status on
  its own row, buttons in a 2×2 grid below — the narrowed ~360px box didn't
  have room for 5 items on one line.
- **Manual Pool Starts overlap — actual root cause found**: it wasn't a
  spacing issue. `QGridLayout.addLayout(bare_vbox, row, col)` (a layout with
  no `QWidget` wrapper) can make Qt miscalculate that cell's row height.
  Fixed by wrapping each label+field pair in a real `QWidget` before adding
  it to the grid — applied to both the Manual Pool Starts grid *and* the
  Telnet fields grid (same pattern, proactively fixed before it could be
  separately reported).
- **Chinese names**: Export Registry's Song column (no separate Order
  column) now shows `"N. 中文名  ·  English"`; Review & Export's Song
  column (already has its own Order column) shows `"中文名  ·  English"`.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`

## Tests performed

- `QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python.exe -m pytest tests/ui/test_show_patch_ma2_discovery.py tests/ui/test_setlist_folder_drag.py tests/exporters tests/persistence -q`: **194 passed**.
- `compileall`: passed.
- No desktop GUI automation available — needs the user's own eyes to
  confirm the pixel result, especially that the overlap is truly gone this
  time.

## Remaining issues

Same outstanding manual-verification checklist as prior 2026-08-08
handoffs — see `.ai/NEXT_TASK.md`.

## Suggested next task

User confirms this round of fixes, then works through the rest of the
manual-verification checklist already queued in `.ai/NEXT_TASK.md`.
