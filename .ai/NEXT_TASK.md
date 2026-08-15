# Next task

**Status:** Awaiting environment repair and user validation
**Type:** Clean Unused Media smoke test
**Updated:** 2026-08-15

## Do this first

1. Restore/recreate `.venv`; its configured Python 3.14 executable is missing.
2. Run:
   `.venv\Scripts\python.exe -m pytest tests/persistence/test_unused_media.py tests/persistence/test_heal_stale_media.py tests/ui/test_duplicate_song_selection.py tests/exporters/test_ma3_song_workflow.py tests/exporters/test_show_patch.py -q`
3. Open the SAX MACHINE project and choose `File → Clean Unused Media…`.
4. Confirm the preview lists only genuinely unused root-level media and protects
   every file referenced inside `Old SET LIST` and `0815 Set List`.
5. Confirm cleanup moves files to `.cueplayer_trash`, then manually restore one
   file to verify recoverability.

## Relevant files

- `src/cueplayer/persistence/unused_media.py`
- `src/cueplayer/ui/main_window.py`
- `tests/persistence/test_unused_media.py`
- `.ai/handoffs/2026-08-15_CleanUnusedMedia.md`
