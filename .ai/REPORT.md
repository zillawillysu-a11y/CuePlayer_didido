# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Item 4 from the user's earlier feedback batch: redesign Review & Export's
"Manual Pool Starts" so each song's Sequence/Effects/Groups/Timecode/View/
Song Macro number can be typed directly per song, per column, with collision
detection, plus an "Auto-Fill" button that sequences a whole queue from seed
numbers. User explicitly chose the full six-Pool-type scope after being
shown the investigation below (not just Sequence/Timecode).

## What was implemented

### Investigation (see the previous handoff for the original findings)

Confirmed via the exporter source that Sequence/Timecode are genuinely
per-song already; Effects/View exist as a per-song *formula* the exporter
recomputes internally (not stored per-song); Song Macro is imported as one
combined block (all songs' macros in one file/Import); and Group Pool never
appeared as an exporter parameter at all (UI/report only, until now).

### Data model

- `MaExportSettings.ma2_pool_overrides: dict[str, dict[str, int]]` — new
  field, `song_id -> {pool_type: start}` for
  `sequence/effects/groups/timecode/view/song_macro`. Persisted generically
  in `project_store.py` (same pattern as `export_content_by_song`).

### Single source of truth (`exporters/show_patch.py`)

- `SongPatchSlot` gained `effect_start`, `group_start`, `view_pool`,
  `song_macro_pool` fields, computed by `build_show_patch()` — the SAME
  place Sequence/Timecode were already computed. Every UI table
  (`playlist_table`, `registry_table`, `review_table`) and the CSV/TXT
  report now read these fields directly instead of re-deriving the formula
  independently in 3+ places (that duplication was the actual root cause of
  the Console-Setup-vs-View-Layout mismatch fixed in the previous task).
- An override "pins" that song's own number without disturbing where the
  running counter puts the *next* (non-overridden) song — verified with a
  dedicated test (`test_manual_pool_override_pins_one_song_without_shifting_others`).
  An overridden Main Sequence also carries its Button sequences along with
  it (`test_manual_sequence_override_carries_its_buttons_along`).
- New `pool_collisions(slots, settings) -> dict[str, set[song_id]]` flags
  any two songs whose ranges overlap in the same Pool type, whether from an
  override or too-small slots-per-song.

### Exporter wiring (`exporters/ma2/exporter.py`) — additive only

All changes are keyed by an optional `pool_overrides` parameter defaulting
to `None`/`{}`; when empty, output is byte-identical to before (verified —
every pre-existing golden-style test in `tests/exporters/test_show_patch.py`
still passes unchanged).

- `export_show_to_directory()` / `write_show_install_plugin()` both gained
  `pool_overrides: dict[str, dict[str, int]] | None = None`.
- **View**: `Import ... At View N` and the View XML's Effects scroll
  position now check `pool_overrides[song_id]["view"]` /
  `["effects"]` before falling back to the existing
  `view_pool_start + index` / `effect_pool_start + index*slots` formula.
- **Song Macro**: new `_song_macro_positions()` /
  `_song_macro_positions_are_contiguous()` helpers. If no override breaks
  the default contiguous block, the single combined
  `Import "..._Song_Macros" At Macro N` stays exactly as before. If one
  does, it falls back to one macro file + one `Import` per song, each at
  its own (possibly non-contiguous) position.
- **Groups**: still has no real object-creation path in the exporter (this
  was true before this task too) — overrides are stored/displayed/reported
  like the other five, but only affect planning numbers, not real Group
  Pool object creation, since that capability doesn't exist in the exporter
  yet. Documented in code and to the user, not silently implied otherwise.
- `SongExportPlan` gained a `song_id: str` field (empty default) so
  show-wide export steps can key overrides back to a song — `common.py` /
  `plan_from_song.py`.

### UI (`ui/show_patch_page.py`)

- `review_table`'s six Pool columns (Sequence/Effects/Groups/Timecode/View/
  Song Macro) are now editable (double-click); `_on_review_table_item_edited`
  parses the leading integer typed, writes/clears
  `settings.ma2_pool_overrides[song_id][pool]`, and refreshes. Colliding
  cells (per `pool_collisions()`) get a red background + tooltip.
- "Manual Pool Starts" box repurposed: dropped the old "Enable manual
  starts" checkbox (which just silently overwrote Console Setup's *global*
  Pool Start — that whole mechanism is superseded by real per-song
  overrides now). Kept the 6 seed fields, added **Auto-Fill & Sequence**
  (writes a sequential override for every song in the queue from the seeds,
  using each Pool's configured slots-per-song as stride) and **Clear All
  Overrides**.
- `_export()`'s MA2 call now passes
  `pool_overrides=self._project.ma_export.ma2_pool_overrides`.
- `_rebuild_playlist_table()`, `_rebuild_workflow_pages()`, and
  `_write_export_allocation_report()` all switched from re-deriving
  Effect/Group/View/Song-Macro numbers via the row-index formula to reading
  `slot.effect_start` / `.group_start` / `.view_pool` / `.song_macro_pool`
  directly — closing the multi-place-duplication risk for good.

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

Overrides are additive/opt-in everywhere: every new parameter defaults to
empty, every formula falls back to the pre-existing behavior when no
override is present. This was deliberate to avoid silently changing any
already-verified export for existing saved projects — confirmed by running
the full pre-existing exporter test suite unchanged (66 tests, all still
passing byte-for-byte) alongside 27 new tests covering the override paths.

Group Pool intentionally was **not** given a real object-creation path in
the exporter — that's a materially different, larger feature (deciding
*what* content each Group holds, which has no data model in this app yet)
outside this task's scope. This is called out explicitly so the user
doesn't assume the override numbers are being enforced on the console for
Groups the way they now are for Sequence/Timecode/View.

## Tests performed

- `QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python.exe -m pytest tests/ui/test_show_patch_ma2_discovery.py tests/ui/test_setlist_folder_drag.py tests/exporters tests/persistence -q`: **193 passed**.
- `compileall` on every touched file: passed.
- No way to visually confirm the new review-table double-click-to-edit
  interaction or collision-red-highlight in the real desktop app from this
  session — logic is fully test-covered, but pixel-level UX needs the
  user's own eyes.

## Remaining issues

- Groups still have no real Pool-object creation in the exporter (see
  above) — planning/report only, same limitation as before this task, now
  just clearly documented.
- The pre-existing full `tests/ui` suite crash (stack overflow, unrelated
  to this branch's work, see the 2026-08-08 Setlist-drag handoff) is still
  unresolved — keep using targeted pytest paths.
- `startup_error.txt` and `.codex-test-tmp/` left untouched.

## Suggested next task

User manually verifies in the running desktop app: double-click a Review &
Export table cell (Sequence/Effects/Groups/Timecode/View/Song Macro),
confirm it becomes editable and the typed number sticks; force a collision
between two songs and confirm the red highlight + tooltip; try Auto-Fill &
Sequence and Clear All Overrides; then do one real MA2 export with at least
one override active and confirm the actual console import lands the
overridden song at the typed Pool number (Sequence/Timecode/View for sure;
Song Macro should split into individual imports if the override breaks
contiguity — check the generated `.lua` for `At Macro` lines).
