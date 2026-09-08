# grandMA3 2.5 Destination Resolution Hotfix

## Task objective
Fix Main cue-name display and the final Button track's missing destination on MA3 2.5.

## What was implemented
Main `CueDestination` now uses the exported cue name, and Sequence-import MacroLines
wait 0.200 seconds before the macro advances.

## Files changed
MA3 exporter, two exporter test modules, report, handoff, and next-task documentation.

## Architecture decisions
Only MA3 XML generation changed; playback and all timecode-output architectures remain untouched.

## Tests performed
69 focused exporter/show workflow tests passed. The full Windows suite encountered
an unrelated WebRTC/UI stack overflow after 64% and is not claimed green.

## Remaining issues
Hardware re-import must confirm both button tracks resolve Cue 1 and Main shows cue names.

## Suggested next task
Perform the MA3 2.5.0.3 verification in `.ai/NEXT_TASK.md`.
