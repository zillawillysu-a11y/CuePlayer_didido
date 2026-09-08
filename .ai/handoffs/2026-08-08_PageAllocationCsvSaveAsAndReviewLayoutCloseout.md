# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

MA2 Exporter close-out round (coordination moved to ChatGPT; this agent codes
only). Seven numbered items, explicitly **not** touching Groups allocation
logic (already verified PASS on real MA2 hardware) or video-waveform:

1. Review & Export UI: remove the oversized bottom-left status text, stop the
   whole page from scrolling, fix the checkbox background/alignment bugs.
2. Make the page a full first-class MA2 allocation item (manual override,
   Auto-Fill, persistence, Live Scan, "Show scan max IDs", "Start after
   scanned Pools" — all already existed for 6 Pool types; extend to Page).
3. Add a Page column to every per-song allocation table, all sourced from the
   same allocation truth.
4. Songs_Pools header: "MA Export Name" → "Export Name" (label only).
5. CSV Allocation Report: make it discoverable via an explicit Save As dialog
   instead of a silent write into the MA2 output folder.
6. Unify the Export Registry / MA2 Live Pool Scan (Telnet) section style.
7. No unrelated refactors; preserve the already-working MA2 export path.

## What was implemented

### 1) Review & Export layout + checkboxes

- Global stylesheet gained a blanket `QCheckBox { background: transparent; }`
  rule — the prior rule was scoped too narrowly and left a dark background
  bar behind "Start after scanned Pools" (Export Registry had the same bug;
  same fix covers both).
- Root-caused the whole-page scroll: an earlier session wrapped every
  workflow tab in `QScrollArea` to fix Console Setup's width overflow. That
  also gave `review_page`/`registry_page`/`songs_page` unlimited height
  instead of the tab's real viewport height, so `review_table`'s `stretch=1`
  row claimed unlimited height and the *whole page* needed to scroll. Fix:
  only `setup_page` and `view_page` (control-heavy, no self-scrolling widget)
  stay wrapped; the three table-driven pages are not, so their own
  `QTableWidget` scrolls internally while the left-side controls stay fully
  visible. Verified offscreen at 1600×800 with 30 songs: left column holds
  its natural height, `review_table` gets the remainder with its own
  scrollbar.
- `review_summary` shrank from a multi-paragraph block to one line
  (`MA2 3.9.63.6 · 30 song(s) · Output: ...`), with the previous detail
  (Groups reserved, Show scan max IDs, override-pin count) moved to a
  tooltip.
- Fixed a stale line in `_scanned_max_text()`: it said "manual overrides
  ignored" while the toggle is on, which contradicted the actual (and
  intended) behavior — manual pins always win. Now reads "Starting after
  these where not manually pinned".
- Telnet/Live Scan box: removed a redundant `setMaximumWidth`, and added
  `setContentsMargins(0,0,0,0)` to standalone sub-layouts (Qt gives
  parent-less layouts non-zero default margins that layouts added directly
  to a parent don't get — this was the actual root cause of the
  misalignment, in both the Telnet section and Manual Pool Starts).

### 2) Page promoted to a full allocation Pool

`build_show_patch()` in `exporters/show_patch.py` is still the single place
that computes every song's allocation. Page now goes through the exact same
machinery as Sequence/Effects/Groups/Timecode/View/Song Macro:

- **Scan**: `Ma2TelnetScanner`'s Lua plugin now also emits
  `CUEPLAYER_SCAN_PAGE=...`; `Ma2PoolSnapshot` gained a `page` field (default
  `frozenset()` so an already-installed older Plugin that predates this still
  parses fine — see Remaining issues).
- **Allocate**: `main_page0` (the first song's Page, parsed from
  `main_executor`) is clamped past `ma2_scanned_pool_max["page"]` when
  **Start after scanned Pools** is on, via the same `_base()` helper used for
  every other Pool.
- **Override**: `ma2_pool_overrides[song_id]["page"]` pins one song's Page
  exactly like the other six keys already did — no new override plumbing was
  needed, `ma2_pool_overrides` was already generic per-key.
- **Auto-Fill**: `"page": (page_start_field.value(), 1)` added to the seeds
  dict — the Manual Pool Starts box already had a "Page" seed field wired to
  nothing meaningful before this; it's now load-bearing.
- **Export**: no exporter-plumbing change was needed. Confirmed by reading
  `plan_from_show_patch()`: `slot.button_executor_start` always embeds
  `slot.page` (via `format_executor(page, btn_exec)`, or the
  `f"{self.page}.201"` fallback when a song has no buttons), and
  `build_export_plan()` parses `profile.page` back out of that same string —
  so `plan.profile.page == slot.page` structurally, override or not. Locked
  in with `test_page_override_flows_into_the_real_export_plan`.

### 3) Page column on every per-song table

`registry_table`, `review_table`, and `playlist_table` all gained a "Page"
column, positioned consistently: `... Timecode / View / Page / Song Macro`.
Every value reads `slot.page` (or the same unqueued-song fallback formula the
tables already used for other columns) — one allocation source, three
displays. `pool_collisions()` gained a `"page"` collision set, but only when
`page_per_song` is on — when every song is deliberately sharing one Page
(`page_per_song=False`), that's by design, not a collision.

### 4) Songs_Pools header rename

`playlist_table`'s header cell changed from "MA Export Name" to
"Export Name". UI label only — `Song.ma_export_name` and every export-name
code path are unchanged.

### 5) CSV Allocation Report — now a Save As action

**It already existed** — silently, as a side effect of every full MA2
export. `_write_export_allocation_report(directory)` wrote both a `.csv` and
a `.txt` straight into the chosen MA2 output folder, with no path shown to
the user beyond a generic file list in the "Export Complete" dialog. That is
exactly why it was hard to find.

Changed:

- CSV generation is no longer part of `_write_export_allocation_report` —
  that function now writes only the `.txt` summary alongside the MA files
  (unchanged location/behavior, since nothing asked for that to move).
- A new **"Export Allocation Report (CSV)…"** button sits next to
  **Refresh Patch** on Review & Export. It calls
  `_export_allocation_report_csv()`, which:
  - Builds columns/rows from a new shared helper,
    `_allocation_report_columns_and_rows()` — this is also what the `.txt`
    writer uses now, so both reports and the on-screen tables all read from
    `self._slots`, never a second computation.
  - Opens `QFileDialog.getSaveFileName(...)` defaulting to
    `<folder of the current Project file>/<Show>_Export_Allocation.csv`, or,
    if the project has never been saved, `QStandardPaths`' Documents
    location (never the MA2 import/export folder).
  - Lets the user rename/relocate freely; `.csv` is enforced as the
    extension.
  - On success, shows a `QMessageBox` with the exact saved path.
  - Cancelling the dialog writes nothing.
- CSV columns are now:
  `Order, Song, Export Name, Sequence, Effects, Groups, Timecode, View, Page,
  Song Macro` — "Song" is the real song title (`slot.song.name`); the
  previous CSV only had one name column and it was actually the *Export*
  name, not the song title.
- `MainWindow` wires `show_patch_page.project_file_path_provider =
  lambda: self._project_path` right after constructing the page, so the
  dialog can find the current Project file's folder without `ShowPatchPage`
  needing a direct `ProjectService` reference.

### 6) Telnet / Live Pool Scan section style

Covered by the same checkbox and margin fixes as (1) — the section's
background/label styling now matches the rest of Export Registry; no theme
redesign.

## Files changed

- `src/cueplayer/exporters/show_patch.py`
- `src/cueplayer/exporters/ma2_telnet.py`
- `src/cueplayer/ui/show_patch_page.py`
- `src/cueplayer/ui/main_window.py`
- `tests/exporters/test_show_patch.py`
- `tests/exporters/test_ma2_telnet.py`
- `tests/ui/test_show_patch_ma2_discovery.py`

## Architecture decisions

- Page's collision/override/scan semantics live entirely inside
  `build_show_patch()` / `pool_collisions()`, exactly where the other six
  Pool types already lived — no parallel code path was created.
- `_allocation_report_columns_and_rows()` is the one place that turns
  `self._slots` into report rows; the TXT writer and the new CSV Save As
  action both call it, so they can't drift from each other or from the
  on-screen tables.
- A page-file-path *provider callable* (not a direct service reference) keeps
  `ShowPatchPage` decoupled from `ProjectService` — matches how the rest of
  this widget already takes settings via plain data, not app-service
  injection.

## Tests performed

- `tests/ui/test_show_patch_ma2_discovery.py` + `tests/exporters/test_show_patch.py`
  + `tests/exporters/test_ma2_telnet.py` + `tests/ui/test_setlist_folder_drag.py`
  + `tests/persistence/test_schema.py` + full `tests/exporters/` +
  `tests/ui/test_transport_main_window_center.py` (constructs a real
  `MainWindow()`, exercising the new `project_file_path_provider` wiring):
  **143 passed**, 0 failed, run with `QT_QPA_PLATFORM=offscreen`.
- New tests added this round (16): Page scan parsing (present + a plugin
  that predates Page scanning), Page moving under Start-after-scanned, Page
  override pinning + flowing into the real export plan, Page collision
  detection (both `page_per_song` states), scan-result wiring the Console
  Setup Page field, CSV columns/rows content, CSV default-directory
  resolution (project-file folder vs. Documents fallback), the Save As
  button writing to the chosen path, and cancelling the dialog writing
  nothing.
- Offscreen geometry re-check at 1600×800 with 30 songs after all edits:
  Songs & Pools / Export Registry / Review & Export are plain `QWidget` tab
  pages (not `QScrollArea`-wrapped); Console Setup / View Layout still are;
  `review_table` shows all 11 columns in the intended order.

## Remaining issues (need Willy's real-MA2 verification)

- **`gma.show.getobj.handle('Page ' .. n)`** — the Lua scanner Plugin now
  calls this the same way it already does for Sequence/Effect/Timecode/
  Macro/View/Group. Whether `'Page'` is a valid `getobj.handle` kind string
  on real MA2 firmware could not be verified from this environment. If the
  console rejects/no-ops it, Page scanning silently returns an empty set
  (`next_free("page")` → 1) rather than erroring — worth one real Scan
  Current Show run to confirm it actually reports real Page numbers.
- An already-installed scanner Plugin from *before* this change (i.e. one a
  user wrote to their MA2 output folder and Imported in an earlier session)
  will not emit `CUEPLAYER_SCAN_PAGE` until **Write Scanner Plugin** is run
  again and the Plugin is re-Imported/re-Installed on the console. This is
  handled gracefully (empty `page` set, no crash) but Willy should re-run
  "Install & Scan" once after pulling this change.
- One real MA2 export with a Page override active, confirming the console
  actually places that song's Main/Buttons on the typed Page — the plan-level
  test (`test_page_override_flows_into_the_real_export_plan`) proves the
  *file* is correct; only a real console import proves MA2 *behaves* on it.
- Visual confirmation in the real desktop app that Review & Export no longer
  scrolls as a whole page, and that the new "Export Allocation Report
  (CSV)…" button + Save As dialog look/feel right — this session's
  verification was entirely offscreen/headless (no GUI automation tool
  available).
- Groups allocation logic was **not touched** in this round, per your
  instruction — its already-verified real-MA2 PASS status stands.

## Suggested next task

1. In the desktop app: open Review & Export, confirm the page no longer
   scrolls as a whole and the Telnet/checkbox styling looks right.
2. Run **Write Scanner Plugin** → **Install & Scan** once against a real
   console; confirm "Show scan max IDs" now includes a Page number and that
   ticking "Start after scanned Pools" moves songs' Pages past it.
3. Click **Export Allocation Report (CSV)…**, confirm the Save As dialog
   opens at the Project file's folder (or Documents if unsaved), and that
   the saved CSV has the 10 expected columns with correct Page numbers.
4. One real MA2 export with a Page override on one song; confirm on-console
   placement matches the typed Page.
