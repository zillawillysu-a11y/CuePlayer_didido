# MA Export Mockup Song Order

## Task objective

Make the Song List Sequence import order explicit in the MA Export playlist workflow.

## What was implemented

- Added a dedicated `Song Order` column beside the export checkbox.
- Song rows display their one-based Song List position.
- Dragging songs updates the visible order automatically.
- Export Review displays the same Song Order for every selected song.
- The song subtitle explains that the number is the Song List position.

## Files changed

- `design/ma_export_playlist_mockup.html`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-07_MAExportMockupSongOrder.md`

## Architecture decisions

- Song Order follows playlist order and is one-based.
- An unselected song retains its playlist position; Review filters it out without renumbering the other songs.
- This prototype change does not alter production exporter behavior.

## Tests performed

- Parsed embedded JavaScript with Node.
- Verified playlist and review Song Order headers and row values.
- Verified drag handling still reorders the shared songs array before rerendering.
- Ran `git diff --check`.

## Remaining issues

- Production UI and Song List Sequence generation still need implementation after design approval.
- Zero-content behavior still needs a product decision.

## Suggested next task

Review and approve Song Order and per-song Main/Button selection, then decide whether selected songs with no content are blocked or skipped.
