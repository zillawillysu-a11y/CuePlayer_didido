# grandMA3 2.5 Destination Resolution Hotfix

Date: 2026-09-09. Branch: `cursor/technical-audit-0815-028d`.

## Task objective

Correct missing Main cue names and the final Button track's missing Cue 1 destination
after importing a CuePlayer full export into grandMA3 2.5.0.3.

## What was implemented

- Main Timecode events now use the actual sanitized MA cue name for
  `CueDestination`, with `Cue N` retained as the unnamed-cue fallback.
- Every MA3 install-macro Sequence import now has a 0.200-second MacroLine wait.
  This prevents the immediately following Timecode import from validating its final
  Sequence before grandMA3 has finished registering that Sequence's cue handles.
- Added regression tests for both behaviors.

## Files changed

- `src/cueplayer/exporters/ma3/exporter.py`
- `tests/exporters/test_latency_compensation.py`
- `tests/exporters/test_ma3_song_workflow.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-09-09_Ma3DestinationResolutionHotfix.md`
- `.ai/NEXT_TASK.md`

## Architecture decisions

The fix is confined to MA3 XML serialization and install-macro pacing. Pool numbers,
numeric cue handles, MA2 behavior, playback, audio, MTC, LTC, and Art-Net are untouched.

## Tests performed

- Focused MA3 exporter/show workflow suite: **69 passed**.
- Full suite progressed beyond 64%, but the existing Windows WebRTC/UI test process
  hit a stack overflow after unrelated failures; this run is not reported as green.
- Hardware evidence compared: CuePlayer source XML, console re-export `TC401.xml`,
  and console re-exports `SEQ2_CHECK.xml` / `SEQ3_CHECK.xml`.

## Remaining issues

Re-export and re-import once on grandMA3 2.5.0.3. Confirm Main Destination shows
`TEST_1` / `TEST_2` and both Mark_3 and Mark_4 show Cue 1. This hardware confirmation
is required before closing the issue.

## Suggested next task

Run the exact grandMA3 2.5.0.3 re-import verification described in `.ai/NEXT_TASK.md`.
