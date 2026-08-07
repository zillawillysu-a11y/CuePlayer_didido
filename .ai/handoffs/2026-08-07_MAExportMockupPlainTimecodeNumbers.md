# MA Export Mockup Plain Timecode Numbers

## Task objective

Remove the redundant `TC` prefix from per-song Timecode pool values in the browser mockup.

## What was implemented

- Song rows now show Timecode values as `201`, `202`, and so on.
- Export Review rows use the same plain numeric format.
- The `Timecode` column heading and Timecode Pool Start setting remain unchanged for context.

## Files changed

- `design/ma_export_playlist_mockup.html`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-07_MAExportMockupPlainTimecodeNumbers.md`

## Architecture decisions

- This is presentation-only; allocation calculations and production exporter behavior are unchanged.

## Tests performed

- Parsed the HTML document.
- Parsed the embedded JavaScript.
- Verified no `TC ${a.timecode}` display remains.
- Ran `git diff --check`.

## Remaining issues

- Production UI implementation remains pending approval of the browser workflow.
- Zero-content behavior still needs a product decision.

## Suggested next task

Review and approve the per-song Main/Button workflow and decide whether selected songs with no content are blocked or skipped.
