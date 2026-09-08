# Inline export content selection

## Task objective

Match the approved HTML playlist interaction by placing Main/Mark checkboxes
directly below the selected song row.

## What was implemented

- Replaced the popup Content menu with an inline expandable playlist row.
- The summary button displays `x/y selected`; clicking it shows checkboxes for
  Main and every eligible Button/Mark under that song.
- Kept the same persisted selection and exporter behavior from the prior task.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-08_InlineExportContentSelection.md`

## Architecture decisions

- This is a presentation-only adjustment. The domain selection format and
  exporter planning remain unchanged.

## Tests performed

- Focused offscreen UI, MA export, and persistence suite: **29 passed**.

## Remaining issues

- A real MA2 import should still validate a mixed Main-only/Button-only set.
- `startup_error.txt` remains untouched.

## Suggested next task

Validate the mixed per-song selections in MA2, then fix only native-console
differences if found.
