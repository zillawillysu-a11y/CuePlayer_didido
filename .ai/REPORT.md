# grandMA3 2.5 Zero-Based Timecode Handle Fix

Date: 2026-09-09. Branch: `cursor/technical-audit-0815-028d`.

## Task objective

Fix unresolved or incorrectly resolved MA3 2.5 Timecode cue destinations using a
same-object 2.3.2/2.5.0.3 console-export comparison.

## What was implemented

- Corrected MA3 2.5 Timecode handles to remain zero-based (`pool - 1`).
- Retained the 2.5 handle-kind change from `5` to `6`.
- Main `CueDestination` continues to use the real exported cue name, with `Cue N`
  fallback for unnamed cues.
- Removed the disproven 0.200-second MacroLine wait workaround.
- Updated regression tests and profile documentation.

## Files changed

MA3 exporter, exporter tests, MA3 profile documentation, report, handoff, and next task.

## Architecture decisions

The same-object console exports are authoritative: Sequence 201 is `.5.200` on
MA3 2.3.2 and `.6.200` on MA3 2.5.0.3. Pool indexing does not change between
versions; only the handle kind changes. No playback or output architecture changed.

## Tests performed

- Focused MA3 exporter/show workflow suite: **68 passed**.
- Compileall passed.
- Git diff check passed.

## Remaining issues

Real-console verification is required. For Sequence pools 1/2/3, exported 2.5 handles
must now be `.6.0/.6.1/.6.2`, and all destinations must survive console import.

## Suggested next task

Run the exact real-console verification in `.ai/NEXT_TASK.md` and re-export the
imported Timecode if any destination still fails.
