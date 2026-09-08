# Handoff — MA2 View Sequence First Cell

**Date:** 2026-08-07
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Correct the Sequence row position in generated MA2 Song Views.

## What was implemented

Sequence scroll now uses `Main Sequence - 1`; Main Sequences 1, 21, and 41 appear as the first pool item instead of the fourth.

## Files changed

- `src/cueplayer/exporters/ma2/exporter.py`
- `tests/exporters/test_show_patch.py`

## Architecture decisions

The calculation follows observed MA2 onPC rendering. No allocation or unrelated behavior changed.

## Tests performed

- Relevant pytest slice: **22 passed**.
- Three-song first-cell regression, `compileall`, and `git diff --check` passed.

## Remaining issues

Re-test the corrected XML in MA2 onPC. `startup_error.txt` was untouched.

## Suggested next task

Confirm first-cell Sequence positioning for Songs 1–3 on the console.
