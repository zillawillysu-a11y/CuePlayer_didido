# Next task

**Status:** Queued — awaiting human start
**Type:** MA2 connection and minimum-version compatibility review
**Updated:** 2026-08-07
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

## Current task

Review the MA2 Telnet scan connection UI and the product-wide grandMA2 3.3.4.3 minimum-version requirement.

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
- View Inspector intentionally omits Column, Row, Columns, Rows, and Visible Pool Slots; position and size are controlled directly on the canvas.
- Pool title cells show only the Pool name, wrap long labels, and use color to communicate Fixed versus Per Song allocation.
- Pool Start and Reserved Slots Per Song are displayed side by side in the Inspector.
- Export Registry keeps Existing allocations stable by Song ID and displays Sequence, Effects, Timecode, Macro, and View usage.
- New songs support Auto Allocate and Manual Allocate with immediate conflict details.
- Incremental components exclude Song List Sequence while including Song Sequences, Timecode, Song Macros, and Song View.
- View previews use registered or pending allocations instead of recalculating Existing songs from Song Order.
- MA2 Live Pool Scan exposes Host, version, command port 30000, monitor port 30001, credentials, Test, and Scan controls.
- grandMA2 3.3.4.3 is the minimum supported version across XML, Plugins, Views, Registry scanning, and Telnet integration.
- The UI connection buttons remain prototypes until real sockets and 3.3.4.3 fixtures are implemented.
- Switching the preview song substitutes that song's Sequence and Effect Pool ranges without moving the shared template.
- Confirm the default Fixed/Per Song modes, Pool starts, and reserved-slot values.
- Decide whether a selected song with no content should be blocked or automatically skipped.

## Done when

The user approves the scan workflow and the 3.3.4.3 compatibility verification plan.
