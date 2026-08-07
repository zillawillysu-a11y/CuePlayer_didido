# MA2 View Allocation Field Layout

## Task objective

Place Pool Start and Reserved Slots Per Song side by side in the View Inspector.

## What was implemented

- Removed the full-row span from Reserved Slots Per Song.
- Pool Start now occupies the left column.
- Reserved Slots Per Song now occupies the right column.
- Both short numeric inputs use equal widths.

## Files changed

- `design/ma_export_playlist_mockup.html`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-07_MA2ViewAllocationFieldLayout.md`

## Architecture decisions

- This is layout-only and does not change allocation values, synchronization, validation, or persistence design.

## Tests performed

- Parsed embedded JavaScript with Node.
- Verified Pool Start and Reserved Slots are sibling non-wide fields in the same two-column grid.
- Ran `git diff --check`.

## Remaining issues

- Production persistence and MA2 XML generation remain pending.
- Other allocation defaults still need review.
- Zero-content song behavior remains undecided.

## Suggested next task

Continue visual review of the shared View Layout, then confirm remaining allocation defaults and zero-content behavior.
