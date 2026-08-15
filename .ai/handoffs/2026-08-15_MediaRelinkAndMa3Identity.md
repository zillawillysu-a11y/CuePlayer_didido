# Media relink and MA3 identity handoff

## Task objective

Fix duplicate-media relinking, make MA3 Page Change use the first Main Sequence,
and prevent duplicate song names from selecting the wrong MA3 objects.

## What was implemented

- Prefer the legacy flat `Media/<basename>` source during stale-path healing.
- Match the supplied PAGE CHANGE command shape and dynamically derive the first
  Main Sequence for the exclusion range.
- Assign colliding MA song names pool-qualified unique identities and propagate
  them through all name-linked MA3 objects and files.
- Added focused regression tests.

## Files changed

- `src/cueplayer/persistence/media_layout.py`
- `src/cueplayer/exporters/plan_from_song.py`
- `src/cueplayer/exporters/show_patch.py`
- `src/cueplayer/exporters/ma3/exporter.py`
- `tests/persistence/test_heal_stale_media.py`
- `tests/exporters/test_ma3_song_workflow.py`
- `tests/exporters/test_show_patch.py`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-15_MediaRelinkAndMa3Identity.md`

## Architecture decisions

- Persistence owns media path recovery.
- Show patch planning owns unique MA object identity; XML writers consume it.
- No playback or clock behavior changed.

## Tests performed

- `git diff --check` passed apart from expected LF/CRLF notices.
- Focused tests were added but could not execute: `.venv` references a removed
  Python 3.14 installation and no alternate Python launcher is installed.

## Remaining issues

- Restore Python and run focused tests.
- Validate affected project relinking in the app.
- Validate PAGE CHANGE and duplicate-name behavior in MA3 2.3.2.

## Suggested next task

Restore `.venv`, execute the three focused suites, then perform the affected
project and MA3 onPC smoke tests described in `.ai/NEXT_TASK.md`.
