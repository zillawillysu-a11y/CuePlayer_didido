# MA2 Shared View Pool Allocation

## Task objective

Use the supplied grandMA2 Pool types and define one shared View layout with independently selectable Fixed or Per Song Pool number allocation.

## What was implemented

- Added all 19 grandMA2 Pool window names shown in the user's reference.
- Removed non-MA2 prototype types such as Template Effect.
- Confirmed Screen 3 is permanently fixed at 16 × 8.
- Standardized on one shared geometry for all songs.
- Added a Fixed/Per Song selector to each Pool window.
- Added configurable base Pool Start and Reserved Slots Per Song.
- Per Song preview numbers advance by Song Order.
- Added same-type Pool range collision validation across fixed and per-song ranges.
- Updated defaults to Sequence (Per Song), Macros (Fixed), Effects (Per Song), and Effects (Fixed).
- Added `docs/MA2_VIEW_LAYOUT_SPEC.md` as the durable product rule.

## Files changed

- `design/ma_export_playlist_mockup.html`
- `docs/MA2_VIEW_LAYOUT_SPEC.md`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-07_MA2SharedViewPoolAllocation.md`

## Architecture decisions

- Screen 3 grid size is a non-configurable 16 × 8 invariant.
- Geometry is shared across songs; only Per Song Pool numbers change.
- Visible cells and reserved allocation stride are intentionally separate.
- Collision checks compare number ranges only among windows of the same Pool type.

## Tests performed

- Parsed embedded JavaScript with Node.
- Verified all 19 Pool names appear in the selector.
- Verified Fixed and Per Song controls and stride logic are present.
- Verified obsolete Apply Template behavior was removed.
- Verified HTML IDs remain unique.
- Ran `git diff --check`.

## Remaining issues

- User review of allocation modes and defaults is required.
- Production persistence and MA2 View XML generation are not implemented.
- Zero-content song behavior remains undecided.

## Suggested next task

Review the Fixed/Per Song controls and confirm default starts/strides, then decide whether zero-content songs are blocked or skipped.
