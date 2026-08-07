# Next task

**Status:** Queued — awaiting human start
**Type:** MA2 Full Export console validation
**Updated:** 2026-08-07
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

## Current task

Smoke-test the generated Full Export Plugin in grandMA2 onPC 3.9.60 and 3.9.61.

## Verify

- Fixed control Macros import at the configured Macro Pool Start.
- Song Macros follow without overlap.
- Template Page is created and named.
- Song List Sequence is assigned to Template Page executor 130.
- Song navigation macros work.
- Per-song Sequences and Timecodes install correctly.
- Generated XML uses the matching 3.9.60 or 3.9.61 schema.

## Done when

Both supported MA2 versions have recorded smoke-test results; any console-specific command incompatibility has a regression test and focused fix.
