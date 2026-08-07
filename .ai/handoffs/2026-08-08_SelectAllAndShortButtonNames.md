# Select all export content and short Button labels

## Task objective

Add a one-song Select All control and remove the song prefix from exported
Button Sequence labels.

## What was implemented

- Added **Select All** beside Clear Selection in each inline Export Content
  row; it selects Main and every eligible Button for that song.
- Button Sequence labels now use only the Button/Mark name, for example
  `Mark 2`, rather than `SongEnglish_Mark 2`.
- XML filenames retain the song prefix to prevent same-named Button files from
  overwriting each other.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `src/cueplayer/exporters/show_patch.py`
- `src/cueplayer/exporters/plan_from_song.py`
- `tests/exporters/test_show_patch.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-08_SelectAllAndShortButtonNames.md`

## Architecture decisions

- Button label and filename are deliberately separate: short MA labels are
  readable, while song-prefixed filenames remain collision-safe.

## Tests performed

- Focused MA planning/export and offscreen UI suite: **27 passed**.

## Remaining issues

- Two songs with the same Button label may still create duplicate MA Sequence
  labels; pool numbers and XML files remain distinct.
- `startup_error.txt` remains untouched.

## Suggested next task

Validate the mixed per-song selections in MA2, then decide whether duplicate
Button label warnings should be added to the export review.
