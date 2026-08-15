# Latest AI task report

**Date:** 2026-08-15
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Prevent duplicated same-name media from unlinking the original setlist, update
the MA3 Page Change fixed macro to the supplied working shape with a dynamic
first Main Sequence, and prevent duplicate MA song names from selecting the
wrong Sequence/Timecode.

## What was implemented

- Stale media healing now prefers an existing legacy `Media/<basename>` file
  before the recursive unique-basename fallback. A duplicated copy in a nested
  Setlist folder therefore no longer makes the original song Unlinked.
- MA3 Page Change now follows the supplied command order and emits
  `Off Sequence <first-main> Thru - Sequence $"song"`.
- The first Main Sequence is derived from the first exported plan that includes
  Main, including per-song pool overrides.
- Duplicate case-insensitive MA song names receive stable pool-qualified names
  such as `Same_Song_S201`; the same identity is used for Sequence, Timecode,
  Page, View, song Macro, and generated filenames.
- Added regression coverage for all three failures.

## Files changed

- `src/cueplayer/persistence/media_layout.py`
- `src/cueplayer/exporters/plan_from_song.py`
- `src/cueplayer/exporters/show_patch.py`
- `src/cueplayer/exporters/ma3/exporter.py`
- `tests/persistence/test_heal_stale_media.py`
- `tests/exporters/test_ma3_song_workflow.py`
- `tests/exporters/test_show_patch.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-15_MediaRelinkAndMa3Identity.md`
- `.ai/NEXT_TASK.md`

## Architecture decisions

- Media recovery remains in persistence and uses a deterministic legacy-layout
  candidate before the conservative ambiguous-name fallback.
- MA uniqueness is established once in show patch planning and propagated
  through the export plan, rather than patched independently in XML writers.
- Playback clock and media playback code are untouched.

## Tests performed

- `git diff --check`: passed (line-ending notices only).
- Added three focused regression tests.
- Pytest could not start because `.venv/pyvenv.cfg` points to removed
  `C:\Users\User\AppData\Local\Programs\Python\Python314\python.exe`;
  PowerShell has no other `python`/`py` command available.

## Remaining issues

- Recreate the project virtual environment or install the expected Python, then
  run the focused persistence and MA exporter suites.
- Validate the generated Page Change macro in grandMA3 2.3.2 hardware/onPC.
- Existing project JSON will heal when opened/saved by the corrected app; no
  user project outside the repository was directly overwritten in this task.

## Suggested next task

Restore the Python environment, run the focused regression suites, open the
affected SAX MACHINE project to confirm its original songs relink, export a
two-song duplicate-name MA3 fixture, and validate PAGE CHANGE on MA3 2.3.2.
