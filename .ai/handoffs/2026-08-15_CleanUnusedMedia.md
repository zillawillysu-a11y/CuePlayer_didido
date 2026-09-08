# Clean Unused Media handoff

## Task objective

Add a safe way to clean media files that the current CuePlayer project no
longer references.

## What was implemented

- Added `File → Clean Unused Media…`.
- Scans only recognized media files below the saved project's `Media` folder.
- Protects paths referenced by legacy Audio Tracks, Audio Variants, and Video Clips.
- Shows file count, total size, and a path preview before confirmation.
- Moves confirmed files to a timestamped `.cueplayer_trash/Unused Media ...`
  folder while preserving relative layout; nothing is permanently deleted.
- Added Unicode, Variant, Video, non-media and quarantine-layout tests.

## Files changed

- `src/cueplayer/persistence/unused_media.py`
- `src/cueplayer/ui/main_window.py`
- `tests/persistence/test_unused_media.py`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-15_CleanUnusedMedia.md`

## Architecture decisions

- Discovery and quarantine live in persistence with no Qt dependency.
- UI owns preview/confirmation only.
- Cleanup is recoverable and restricted to resolved paths under `Media`.
- Playback engine and clock are untouched.

## Tests performed

- `git diff --check` performed after implementation.
- Focused pytest execution remains blocked because `.venv` references the
  removed Python 3.14 installation and no alternate Python launcher is present.

## Remaining issues

- Restore Python and execute `tests/persistence/test_unused_media.py` plus the
  previously added media/duplicate/MA3 regression suites.
- Smoke-test the preview against the SAX MACHINE project before confirming a move.

## Suggested next task

Restore `.venv`, run the focused suites, open SAX MACHINE, use Clean Unused
Media to review the 11 root-level files, and confirm quarantine/restore behavior.
