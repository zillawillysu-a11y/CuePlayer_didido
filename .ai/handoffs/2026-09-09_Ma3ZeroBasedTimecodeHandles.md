# grandMA3 2.5 Zero-Based Timecode Handles

## Task objective
Correct MA3 2.5 cue destinations using matched 2.3/2.5 console exports.

## What was implemented
2.5 now emits handle kind 6 with the same zero-based `pool - 1` index as 2.3;
Main destination labels retain actual cue names. The invalid wait workaround was removed.

## Files changed
MA3 exporter, exporter tests, MA3 profile docs, report, handoff, and next task.

## Architecture decisions
Matched console evidence supersedes the earlier inference from unrelated TC301 pools.

## Tests performed
68 focused tests passed; compileall and diff checks passed.

## Remaining issues
Verify the corrected `.6.0/.6.1/.6.2` handles on grandMA3 2.5.0.3.

## Suggested next task
Perform the verification recorded in `.ai/NEXT_TASK.md`.
