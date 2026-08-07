# Next task

**Status:** Queued — awaiting human start
**Type:** MA Export UI and View Layout design review
**Updated:** 2026-08-07
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

## Current task

Review the updated browser mockup with per-song Main/Button content selection and the interactive Screen 3 View Layout editor.

## Verify

- Timecode Pool Start 201 is visible and understandable.
- Template Page 200, Fixed Macro 101, and Song Macro 201 defaults are correct.
- Main Executor 201.130 and Button Start 201.101 defaults are correct.
- Expanding each song and selecting Main/Button content feels intuitive.
- Review clearly communicates what each song will export.
- All interface chrome is English while Unicode song names remain readable.
- Timecode values appear as plain pool numbers (`201`, `202`) without a redundant `TC` prefix.
- Song Order is explicit in both the playlist and review, and drag reordering updates the Song List Sequence order.
- View Layout Pool windows use the verified Screen 3 `16 × 8` grid and can be selected, dragged, resized by whole cells, locked, duplicated, deleted, and edited numerically.
- Every Pool title consumes one full grid cell; visible capacity is `columns × rows - 1`, and overlap is reported.
- Screen 3 is permanently fixed at 16 × 8 and is never user-configurable.
- All songs share one View geometry; every Pool independently selects Fixed or Per Song allocation.
- The Pool Type menu contains the supplied grandMA2 Pool names, and same-type number ranges are checked for overlap.
- Per Song Effects reserve 100 Pool numbers by default, allow any valid value from 1, and stay synchronized between Common Settings and View Inspector.
- View Inspector intentionally omits Column, Row, and Visible Pool Slots; only Columns/Rows sizing and allocation controls are shown.
- Switching the preview song substitutes that song's Sequence and Effect Pool ranges without moving the shared template.
- Confirm the default Fixed/Per Song modes, Pool starts, and reserved-slot values.
- Decide whether a selected song with no content should be blocked or automatically skipped.

## Done when

The user approves the playlist and shared View Layout workflows, confirms allocation defaults, and defines zero-content behavior.
