# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

User ran the desktop app and gave 7 pieces of feedback from real screenshots
(the manual visual test earlier sessions couldn't perform): label ordering,
a real bug (Show Name not reaching the exported Song List/Template Page), a
Console Setup field-organization request, a new "follow Console Setup"
concept for View Layout Pools, a request to reflow the export-confirm
dialog, a Telnet-login convenience default, and — mid-turn — three page
layout requests (Songs & Pools, Export Registry, Review & Export each go
from stacked boxes to left/right or left/middle/right columns so more rows
are visible without scrolling).

## What was implemented

1. **Export Queue label order** — `_rebuild_song_pick` now shows
   `{Chinese name} · {English name}` instead of English-first.
2. **Real bug fix**: `_export()`'s MA2 branch never passed `show_name=` to
   `Ma2Exporter.export_show_to_directory`, so the exported Plugin's Song
   List / Template Page labels always used the "CuePlayer" default no
   matter what Show Name was configured. Added the missing kwarg.
3. **Console Setup Pool Start consolidation** — Effect/Group/View/Song
   Macro/Fixed Macro Start (previously buried in the "Export Options" grid)
   now live in the "Pool Start" box alongside Sequence/Timecode, as a 2-col
   grid: Sequence, Effect, Group, Timecode, View, Song Macro, Fixed Macro.
4. **View Layout "Follow Console Setup" checkbox** — new per-Pool-widget
   checkbox in the Pool Inspector, enabled only for Pool Types with a real
   per-song Console Setup counterpart (sequence/effects/groups/
   timecode/macros). Checked: Pool Start/Stride/Allocation are derived live
   from the matching Console Setup field (forced to Per Song) and the
   spinboxes go read-only; a new `_sync_following_view_pools()` (called from
   `_write_ui_to_settings`) keeps them in step whenever Console Setup
   changes. Unchecked: independent, exactly as before. This **replaces** the
   old one-directional, inconsistent auto-push (View Layout → Console Setup)
   that only existed for Sequence/Effects and silently ignored
   Groups/Timecode/Macro — that was the actual root cause of the
   Console-Setup-vs-View-Layout number mismatch the user saw (201 vs 509 in
   their screenshot).
5. **Export-confirm dialog** — "Enabled content" is now one bullet per line
   instead of a single comma-joined string.
6. **Telnet login defaults** — `MA2 Show User`/`Password` now default to
   `administrator`/`admin` (grandMA2's own stock login) instead of blank/
   `CuePlayerScan`, everywhere that default is read (widget construction,
   `_load_settings_into_ui`, `_write_ui_to_settings`, the `MaExportSettings`
   dataclass default, and `project_store.py`'s load fallback).
7. **Page layout reflow** (mid-turn follow-up, all three requested in one
   message with screenshots):
   - **Songs & Pools**: Export Queue is now a narrower left column
     (max 340px), `playlist_table` fills the right column — frees vertical
     space so more songs are visible without scrolling.
   - **Export Registry**: three columns — Telnet scan controls (left),
     the 4 stat tiles stacked vertically + registry status (middle),
     `registry_table` (right, wider).
   - **Review & Export**: Export Content Check + Manual Pool Starts (now a
     2-col grid instead of 6-across) + summary text form a left column;
     `review_table` fills the right column.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `src/cueplayer/domain/models.py` (`ma2_telnet_user` default)
- `src/cueplayer/persistence/project_store.py` (load fallback)
- `tests/ui/test_show_patch_ma2_discovery.py`

## Architecture decisions

The "follow" feature intentionally derives numbers from Console Setup
*live* (via `_write_ui_to_settings` → `_sync_following_view_pools`) rather
than copying them once, so a later Console Setup edit doesn't silently
desync a Pool the user already told to follow it. "follow" defaults to
`False`/absent on every widget dict, so existing saved projects and their
already-exported Pool numbers are unaffected on load — this is purely
opt-in.

## Tests performed

- `QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python.exe -m pytest tests/ui/test_show_patch_ma2_discovery.py tests/ui/test_setlist_folder_drag.py -q`: **27 passed**.
- `compileall` on all touched files: passed.
- Rewrote `test_view_allocation_controls_drive_shared_export_settings` (it
  asserted the OLD one-directional push-sync this task removed) into
  `test_view_pool_start_is_independent_of_console_setup_unless_following`,
  and added `test_follow_checkbox_mirrors_console_setup_pool_start` +
  `test_follow_checkbox_only_available_for_console_pool_types`.
- No way to visually confirm the 3-page layout reflow in the real desktop
  app from this session (no desktop GUI automation available) — logic and
  widget wiring are test-covered, but the actual pixel layout needs the
  user's own eyes.

## Remaining issues — item 4 needs a decision before implementing

The user's 4th request ("Review & Export → Manual Pool Starts should let me
type a starting Pool number **per song, per Pool column**, with collision
detection, plus an auto-fill button that sequences them") was investigated
but **not implemented** this session. Investigation found:

- `SongPatchSlot.main_sequence` and `.timecode_pool` (in
  `exporters/show_patch.py::build_show_patch`) are genuinely computed
  per-song in a loop and flow straight into the real exported XML via
  `plans_from_show_patch` — a true per-song override for Sequence and
  Timecode is safe and would actually change the export.
- Effect/View/Song Macro pool numbers are **not** per-song fields anywhere;
  `Ma2Exporter.export_show_to_directory` takes them as single global
  `effect_pool_start` / `effect_slots_per_song` / `view_pool_start` /
  `song_macro_start` scalars and presumably re-derives each song's number
  internally via the same linear formula the UI displays.
- **Group pool** does not appear as a parameter to
  `export_show_to_directory` **at all** — strong sign Groups aren't wired
  into the real MA2 XML/Plugin output yet, only into the UI tables and the
  CSV/TXT allocation report.

Building "type any number, it exports exactly as typed" for Effects/Groups/
View/Song Macro would require first extending the exporter's internal
Pool-assignment logic to accept explicit per-song values instead of a
global formula — a correctness-critical exporter change, not just a UI
change, and one that needs verifying whether Groups export at all today.
Given PRODUCT_SPEC's non-negotiable MA export correctness, this needs the
user's explicit go-ahead on scope before touching it (see next task).

## Suggested next task

Ask the user to confirm scope for item 4 (Manual Pool Starts redesign)
before building: (a) full per-song override + collision detection for all
six Pool types, which first requires extending `Ma2Exporter` to accept
per-song Effect/Group/View/Song-Macro assignments instead of a global
formula, and confirming whether Groups export at all today; or (b) a
smaller first slice — true per-song override + collision detection for
Sequence and Timecode only (already genuinely per-song in the exporter),
leaving Effects/Groups/View/Song Macro on the existing formula for now.
Separately, the user should visually confirm the three page-layout changes
in the running desktop app.
