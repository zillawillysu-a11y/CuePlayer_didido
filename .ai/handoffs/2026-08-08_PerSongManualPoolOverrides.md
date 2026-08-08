# Per-Song Manual Pool Overrides (Item 4, Full Six-Type Scope)

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

User chose the full six-Pool-type scope for the "Manual Pool Starts"
redesign: type a specific starting Pool number per song, per column
(Sequence/Effects/Groups/Timecode/View/Song Macro) in Review & Export, with
collision detection, plus an Auto-Fill button that sequences a whole queue
from seed numbers.

## What was implemented

See `.ai/REPORT.md` for the full technical breakdown. Summary:

- New `MaExportSettings.ma2_pool_overrides: dict[song_id, dict[pool_type, start]]`,
  persisted like `export_content_by_song`.
- `SongPatchSlot` (in `exporters/show_patch.py`) gained `effect_start`,
  `group_start`, `view_pool`, `song_macro_pool` — now the single source of
  truth every UI table and the CSV/TXT report read from directly, closing a
  three-way duplication that was the actual cause of the earlier
  Console-Setup-vs-View-Layout mismatch. Overrides "pin" one song without
  shifting anyone else. New `pool_collisions()` flags overlapping ranges.
- `Ma2Exporter` gained an additive `pool_overrides` parameter, threaded into
  the real export: View import position + Effects scroll position now check
  overrides first; Song Macro splits into per-song imports only when an
  override breaks the default contiguous block (otherwise identical to
  before). Verified byte-identical output when `pool_overrides` is empty —
  all 66 pre-existing exporter tests pass unchanged.
- Groups still has **no real object-creation path** in the exporter (true
  before this task too) — overrides for Groups remain planning/report-only,
  clearly documented rather than silently implied to be enforced.
- `review_table`'s six Pool columns are now double-click editable, write
  into `ma2_pool_overrides`, and highlight collisions red with a tooltip.
  "Manual Pool Starts" box repurposed: dropped the old checkbox (which just
  overwrote Console Setup's global start), added **Auto-Fill & Sequence**
  and **Clear All Overrides** buttons.

## Files changed

- `src/cueplayer/domain/models.py`
- `src/cueplayer/persistence/project_store.py`
- `src/cueplayer/exporters/show_patch.py`
- `src/cueplayer/exporters/common.py`
- `src/cueplayer/exporters/plan_from_song.py`
- `src/cueplayer/exporters/ma2/exporter.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_show_patch.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `tests/persistence/test_schema.py`

## Architecture decisions

Every new code path is additive and opt-in — defaults to empty/`None`,
falls back to the pre-existing formula when unused, so no already-verified
export for an existing saved project changes unless the user actively adds
an override. Confirmed by running the complete pre-existing exporter test
suite unchanged alongside the new override-path tests.

## Tests performed

- `QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python.exe -m pytest tests/ui/test_show_patch_ma2_discovery.py tests/ui/test_setlist_folder_drag.py tests/exporters tests/persistence -q`: **193 passed**.
- `compileall`: passed.
- No desktop GUI automation available this session — the double-click-edit
  interaction and collision-highlight visuals need the user's own eyes in
  the running app.

## Remaining issues

- Groups export wiring (real Pool-object creation) remains out of scope —
  would need its own data model for "what content goes in this Group",
  unrelated to just assigning a number.
- Pre-existing full `tests/ui` suite stack-overflow crash, unrelated to this
  work (see the earlier Setlist-drag handoff), still unresolved.
- `startup_error.txt` and `.codex-test-tmp/` left untouched.

## Suggested next task

User manually verifies in the desktop app: editing a Review & Export Pool
cell, the collision red-highlight, Auto-Fill & Sequence, Clear All
Overrides, then one real MA2 export with an active override to confirm the
console actually imports the overridden song at the typed number
(Sequence/Timecode/View for sure; check the generated `.lua`'s `At Macro`
lines for Song Macro if that override was used, since it changes from one
combined import to several).
