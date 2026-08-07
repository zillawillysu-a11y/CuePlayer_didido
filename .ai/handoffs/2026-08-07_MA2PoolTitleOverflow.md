# MA2 Pool Title Overflow

## Task objective

Prevent Sequence and other MA2 Pool names from overflowing their one-cell title area.

## What was implemented

- Removed Fixed/Per Song and slot-count text from inside the Pool title cell.
- Kept allocation mode visible through the existing purple/blue color coding and legend.
- Added responsive title font sizing.
- Added safe wrapping for longer MA2 Pool names.
- Reduced title padding and line height to fit one Screen 3 cell.

## Files changed

- `design/ma_export_playlist_mockup.html`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-07_MA2PoolTitleOverflow.md`

## Architecture decisions

- Pool Title continues to occupy exactly one grid cell.
- Allocation metadata belongs in the Inspector and legend rather than inside the constrained title cell.
- No allocation or geometry behavior changed.

## Tests performed

- Parsed embedded JavaScript with Node.
- Verified title markup contains only the Pool name.
- Verified obsolete title `small` metadata is absent.
- Verified responsive wrapping CSS is present.
- Ran `git diff --check`.

## Remaining issues

- Visual review of all long Pool names is still useful.
- Production persistence and MA2 XML generation remain pending.
- Zero-content song behavior remains undecided.

## Suggested next task

Continue visual review of the shared View Layout, then confirm remaining allocation defaults and zero-content behavior.
