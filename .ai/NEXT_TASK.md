# Next task

**Status:** Queued — awaiting human start
**Type:** MA2 Full Export console validation
**Updated:** 2026-08-07
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

## Current task

Smoke-test the revised Full Export Plugin in grandMA2 onPC 3.9.60 and 3.9.61.

## Verify

- Fixed and Song Macros import at their independently configured pool starts.
- Optional `Preset` cue is created at the configured Cue ID on every Main Sequence.
- A conflicting Preset Cue ID produces a clear export error.
- Song List starts at Cue 1 and contains songs only.
- Main Sequence and Timecode labels are the English song name without suffixes.
- Template Page executor 130 and per-song Timecodes still install correctly.

## Done when

Both supported MA2 versions have recorded smoke-test results and any console-specific incompatibility has a regression test and focused fix.
