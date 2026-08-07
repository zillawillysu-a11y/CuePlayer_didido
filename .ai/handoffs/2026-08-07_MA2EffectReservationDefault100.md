# MA2 Effect Reservation Default 100

## Task objective

Default to reserving 100 Effect Pool numbers for every song without a special minimum.

## What was implemented

- Added `Effect Slots Per Song` to Common Settings.
- Default Effect reservation is 100 and the general minimum is 1.
- Playlist Effect ranges now advance using this configurable reservation.
- Default Per Song Effects View allocation stride changed from 80 to 100.
- View Inspector allows any valid reserved stride from 1.
- Common Settings and Per Song Effects View strides are synchronized in both directions.
- Fixed Effects remain unrestricted because they do not advance by Song Order.

## Files changed

- `design/ma_export_playlist_mockup.html`
- `docs/MA2_VIEW_LAYOUT_SPEC.md`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-07_MA2EffectReservationDefault100.md`

## Architecture decisions

- Visible capacity remains independent from allocation stride.
- A 16 × 5 Effects window displays 79 objects but reserves 100 numbers per song by default.
- Effects have no special minimum beyond the general value of 1.

## Tests performed

- Parsed embedded JavaScript with Node.
- Verified Common Settings default is 100 and minimum is 1.
- Verified Per Song Effects default stride is 100.
- Verified playlist allocation uses the configurable Effect slot count.
- Verified View Inspector accepts valid stride values from 1.
- Ran `git diff --check`.

## Remaining issues

- Production persistence and MA2 XML generation remain pending.
- User confirmation of other Pool allocation defaults is still required.
- Zero-content song behavior remains undecided.

## Suggested next task

Review remaining Fixed/Per Song Pool defaults and decide whether zero-content songs are blocked or skipped.
