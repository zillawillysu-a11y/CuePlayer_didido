# MA Export Five Page PySide Layout

## Task objective

Make the approved five-stage MA Export workflow visible in the production PySide6 application instead of only in the HTML mockup.

## What was implemented

- Added five production workflow tabs.
- Rehomed existing song/settings/export controls without rewriting exporter behavior.
- Added derived Registry and Review tables.
- Added a fixed 16×8 Screen 3 Pool allocation preview.
- Kept version discovery, Output Folder modes, and Registry synchronization working.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-08_MaExportFivePagePySideLayout.md`

## Architecture decisions

- UI composition only; existing exporters remain authoritative.
- Registry/Review/View are derived from current project settings.
- View geometry is fixed to 16×8, with a read-only preview in this slice.

## Tests performed

- 24 final focused tests passed.
- 30 broader tests passed before the final layout-only stretch adjustment.
- Offscreen Qt screenshots for all pages were rendered and inspected.
- `git diff --check` passed.

## Remaining issues

- Production View drag/resize and persistence remain.
- Per-song Main/Button selection remains.
- Real MA occupancy scan remains blocked on future Telnet transport.
- `startup_error.txt` was not touched.

## Suggested next task

Implement per-song content selection plus the persisted interactive 16×8 View editor, preserving all completed production discovery/export behavior and excluding Telnet.
