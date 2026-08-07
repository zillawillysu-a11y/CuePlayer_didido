# Per-song MA export content selection

## Task objective

Let users choose Main and individual Button content for every exported song.

## What was implemented

- Persisted selections per song with all-content defaults for existing shows.
- Added the Content selector in the export playlist.
- Filtered sequence allocation, MA2/MA3 files, installer commands, and
  Timecode tracks according to the selection.
- Ensured Button-only exports start at the assigned sequence number without a
  hidden Main sequence consuming it.

## Files changed

- `src/cueplayer/domain/models.py`
- `src/cueplayer/persistence/project_store.py`
- `src/cueplayer/exporters/common.py`
- `src/cueplayer/exporters/plan_from_song.py`
- `src/cueplayer/exporters/show_patch.py`
- `src/cueplayer/exporters/ma2/exporter.py`
- `src/cueplayer/exporters/ma3/exporter.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_show_patch.py`
- `tests/persistence/test_schema.py`
- `tests/ui/test_show_patch_ma2_discovery.py`

## Architecture decisions

- Selection is persisted as export configuration and interpreted by the show
  planning layer, keeping UI and exporter responsibilities separated.

## Tests performed

- Focused exporter, persistence, plan, and offscreen UI suite: **32 passed**.

## Remaining issues

- Needs a real MA2 import with mixed selection states.
- `startup_error.txt` remains untouched.

## Suggested next task

Validate mixed per-song content selection in MA2, then address only observed
native-console differences.
