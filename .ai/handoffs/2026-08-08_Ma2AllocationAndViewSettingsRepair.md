# MA2 allocation and View settings repair

## Completed

- Added persisted `ma2_effect_slots_per_song` (default 100).
- MA2 song View XML now advances Effect windows by that value instead of 80.
- Restored current Timecode/Executor/Page/Macro defaults when loading untouched legacy settings.
- Persisted MA2 target version and output-folder follow mode.
- Added working English View Allocation controls and per-song preview.
- Synchronized playlist, Registry, Review, View preview, and exporter allocation math.

## Verification

- Focused persistence, MA2 exporter, and Show Patch UI tests: 19 passed.
- Python compile and `git diff --check`: passed.
- Full suite was stopped after more than one minute without output; it had not reported a failure.

## Next

Implement per-song Main/Button content selection and the draggable/resizable persisted 16×8 View layout.

`startup_error.txt` was not modified.
