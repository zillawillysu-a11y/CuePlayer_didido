# MA Export Screen 3 Grid Correction

## Task objective

Correct the View Layout prototype to use the exact Screen 3 Pool-cell system demonstrated in the user's reference screenshots.

## What was implemented

- Replaced percentage/freeform geometry with a fixed 16-column by 8-row grid.
- Changed the canvas to a 2:1 Pool-area ratio so the 16 × 8 cells are square.
- Drag and resize operations now move only by complete Pool cells.
- Pool Title is rendered as the first full cell inside every Pool window.
- Visible Pool capacity is calculated automatically as `columns × rows - 1`.
- Inspector fields now use Column, Row, Columns, and Rows instead of percentages.
- Added overlap detection and a visible warning.
- Updated the default layout to match the reference structure:
  - Sequence: 10 × 1 = 9 visible slots.
  - Group: 6 × 1 = 5 visible slots.
  - Effect: 16 × 5 = 79 visible slots.
  - Template Effect: 16 × 2 = 31 visible slots.

## Files changed

- `design/ma_export_playlist_mockup.html`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-07_MAExportScreen3GridCorrection.md`

## Architecture decisions

- Screen 3 geometry is represented as integer grid cells; CSS percentages are derived only for display.
- Title capacity is never counted as a usable Pool object slot.
- A 1 × 1 window is valid but shows only its title and zero Pool objects.
- Production XML mapping must preserve these grid bounds and title-cell semantics.

## Tests performed

- Parsed embedded JavaScript with Node.
- Verified no optional percentage snapping remains.
- Verified 16 × 8 canvas dimensions and integer bounds.
- Verified default visible capacities: 9, 5, 79, 31.
- Verified overlap detection exists.
- Ran `git diff --check`.

## Remaining issues

- Compare exact generated MA2 XML geometry against S1View.xml and S2View.xml during production implementation.
- Decide whether the second top-row Pool should default to Group or Macro for the exported song View.
- Decide shared-template versus per-song override behavior.
- Zero-content song export behavior remains undecided.

## Suggested next task

Review the corrected 16 × 8 View Layout and confirm the default top-right Pool type, then define shared-template/per-song override and zero-content behavior.
