# Next task

**Status:** Queued — awaiting human start
**Type:** MA2 Sequence block console validation
**Updated:** 2026-08-07
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

## Current task

Smoke-test MA2 Sequence block allocation and final ViewButton initialization.

## Verify

- With start 1 and 20 slots per song, song Main Sequences use 1, 21, 41, etc.
- Button and manually added Sequences fit inside each song's reserved block.
- Song List is allocated after the final reserved block.
- Generated Song Views show the correct per-song Sequence block.
- Plugin runs `Set Songviewbutton` after all Timecode imports.
- `$songviewbutton` contains the configured ViewButton address.

## Done when

MA2 onPC shows correct reserved pools and ViewButton initialization, with any console-specific incompatibility covered by a regression test and focused fix.
