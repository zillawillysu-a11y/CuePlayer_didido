# Clear one song's export-content selection

## Task objective

Add a direct control to clear all Main/Button export-content checks for the
currently expanded song.

## What was implemented

- Added **Clear Selection** to the inline Export Content row.
- Clearing sets Main to false and the selected Button list to empty.
- The main song Export checkbox remains selected, so clearing content does not
  remove the song from the playlist.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-08_ClearSongExportContentSelection.md`

## Architecture decisions

- Clear uses the existing persisted per-song selection shape; no exporter or
  domain behavior is duplicated in the UI.

## Tests performed

- Focused offscreen UI and MA show-patch suite: **24 passed**.

## Remaining issues

- A real MA2 import should still validate mixed content selections.
- `startup_error.txt` remains untouched.

## Suggested next task

Validate the mixed per-song selections in MA2, then fix only native-console
differences if found.
