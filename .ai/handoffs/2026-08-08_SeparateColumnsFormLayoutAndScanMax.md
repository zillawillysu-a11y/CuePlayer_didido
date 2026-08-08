# Separate Order/Chinese/Song Columns, QFormLayout Fix, Live Scan Max Display

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Third round of same-day layout feedback: Chinese name and Order should be
their own separate columns (not combined text) in Export Registry / Review
& Export; Manual Pool Starts still didn't render correctly after two prior
fix attempts; user wants the Live Scan's actual highest-found Pool number
surfaced on Export Registry itself (it already existed, just wasn't shown
there).

## What was implemented

- **Manual Pool Starts**: abandoned the custom grid entirely (two attempts
  had subtle Qt row-height bugs) in favor of a plain `QFormLayout` — the
  same pattern Console Setup's Pool Start box already uses successfully.
- **Separate columns**: `registry_table` (8→10 cols) and `review_table`
  (9→10 cols) now each have distinct Order / Chinese / Song columns instead
  of one combined string cell. Chinese is display-only, never exported.
  Registry's Order shows the setlist number (no other order column there);
  Review's Order keeps its existing export-queue-position meaning.
- **Live Scan max IDs on Export Registry**: factored `_scanned_max_text()`
  (shared with Review & Export, which already showed this) and appended it
  to Export Registry's own status line, next to "Next safe starts" — so
  CuePlayer's own plan and the actual console-scanned max are both visible
  where the scan happens.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`

## Tests performed

- `QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python.exe -m pytest tests/ui/test_show_patch_ma2_discovery.py tests/ui/test_setlist_folder_drag.py tests/exporters tests/persistence -q`: **194 passed**.
- `compileall`: passed.
- No desktop GUI automation available — the Manual Pool Starts fix in
  particular needs careful manual re-verification since two prior attempts
  didn't fully work.

## Remaining issues

Same outstanding manual-verification checklist as prior 2026-08-08
handoffs — see `.ai/NEXT_TASK.md`.

## Suggested next task

User confirms this round of fixes, especially Manual Pool Starts, then
works through the rest of the manual-verification checklist already queued
in `.ai/NEXT_TASK.md`.
