# Next task

**Status:** Awaiting environment repair and user validation
**Type:** Regression validation / MA3 onPC smoke test
**Updated:** 2026-08-15

## Do this first

1. Restore/recreate `.venv` (its configured Python 3.14 executable is missing).
2. Run:
   `.venv\Scripts\python.exe -m pytest tests/persistence/test_heal_stale_media.py tests/exporters/test_ma3_song_workflow.py tests/exporters/test_show_patch.py -q`
3. Open the affected SAX MACHINE project and confirm old songs relink to the
   flat `Media/<filename>` originals while duplicated songs keep their new files.
4. Batch-Duplicate every song in one Folder, move the selected copies to a new
   Folder, and confirm the old Folder still contains all originals.
5. Export two songs with the same MA Export Name and verify the generated MA
   identities are unique and consistent.
6. Import into grandMA3 2.3.2 and validate PAGE CHANGE, especially the dynamic
   `Off Sequence <first-main> Thru - Sequence $"song"` command.

## Relevant files

- `src/cueplayer/persistence/media_layout.py`
- `src/cueplayer/exporters/plan_from_song.py`
- `src/cueplayer/exporters/show_patch.py`
- `src/cueplayer/exporters/ma3/exporter.py`
- `tests/persistence/test_heal_stale_media.py`
- `tests/exporters/test_ma3_song_workflow.py`
- `tests/exporters/test_show_patch.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_duplicate_song_selection.py`
