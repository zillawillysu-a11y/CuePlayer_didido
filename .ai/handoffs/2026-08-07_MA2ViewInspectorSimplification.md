# MA2 View Inspector Simplification

## Task objective

Remove unnecessary Column, Row, and Visible Pool Slots fields from the View Inspector.

## What was implemented

- Removed Column and Row numeric controls.
- Removed the read-only Visible Pool Slots control.
- Kept Columns and Rows for precise window sizing.
- Pool position remains controlled through whole-cell dragging.
- Visible capacity remains internally calculated as `columns × rows - 1`.
- Removed all JavaScript reads, writes, and event bindings for the deleted controls.

## Files changed

- `design/ma_export_playlist_mockup.html`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-07_MA2ViewInspectorSimplification.md`

## Architecture decisions

- The underlying integer x/y geometry remains part of the layout model even though it is not exposed in the Inspector.
- This is a presentation simplification and does not change Screen 3 grid calculations.

## Tests performed

- Parsed embedded JavaScript with Node.
- Verified removed labels and IDs are absent.
- Verified no JavaScript references to removed controls remain.
- Verified Columns, Rows, Pool Start, and allocation controls remain.
- Ran `git diff --check`.

## Remaining issues

- Production persistence and MA2 XML generation remain pending.
- User confirmation of other allocation defaults is still required.
- Zero-content song behavior remains undecided.

## Suggested next task

Continue reviewing the simplified View Layout controls, then confirm remaining allocation defaults and zero-content behavior.
