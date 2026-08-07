# Next task

**Status:** Queued — awaiting human start
**Type:** MA2 Song View console validation
**Updated:** 2026-08-07
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

## Current task

Smoke-test generated Song Views in grandMA2 onPC 3.9.60 and 3.9.61.

## Verify

- Every selected song imports into a consecutive View Pool slot.
- View labels use English song names.
- Views open on Screen 3 with the supplied geometry.
- Sequence row begins at the song's allocated Sequence range.
- Song Effect area advances in non-overlapping 80-slot pages from the configured start.
- Template Effect starts at 1 and Macro area remains fixed.
- Page Change assigns the correct View to the configured ViewButton.

## Done when

Both supported MA2 versions have recorded View import/render results and any console-specific incompatibility has a regression test and focused fix.
