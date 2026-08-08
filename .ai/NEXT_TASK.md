# Next task

**Status:** Blocked — awaiting user's scope decision on item 4
**Type:** MA export workflow UI
**Updated:** 2026-08-08

## Current task

Get the user's decision on the scope of the "Manual Pool Starts" redesign
(Review & Export page): they want to type a specific starting Pool number
per song, per Pool column (Sequence/Effects/Groups/Timecode/View/Song
Macro), with collision detection, plus an auto-fill button that sequences
values across songs from a set of starting numbers.

Investigation (see `.ai/handoffs/2026-08-08_ConsoleSetupUiFixesAndPageLayoutReflow.md`)
found this is **not just a UI change**:

- Sequence and Timecode are genuinely per-song fields
  (`SongPatchSlot.main_sequence` / `.timecode_pool` in
  `exporters/show_patch.py`) that flow straight into the real export — safe
  to make per-song-overridable today.
- Effect/View/Song Macro pools are only ever derived from a single global
  `start + row * slots_per_song` formula inside
  `Ma2Exporter.export_show_to_directory` (`src/cueplayer/exporters/ma2/exporter.py`)
  — there is no per-song field to override yet.
  **Group pool doesn't even appear as a parameter to that function at
  all** — it may not be wired into the real MA2 XML/Plugin output yet,
  only into the UI tables and the CSV/TXT allocation report.

Ask the user to choose:
- (a) Full per-song override + collision detection for all six pool types —
  requires first extending `Ma2Exporter` to accept explicit per-song
  Effect/Group/View/Song-Macro assignments instead of a global formula, and
  confirming/fixing whether Groups are exported to MA2 XML at all today.
- (b) A smaller first slice: true per-song override + collision detection
  for Sequence and Timecode only (already genuinely per-song), leaving the
  other four pool types on the existing global-formula behavior for now.

## Also pending (not blocking)

- User should visually confirm, in the running desktop app, the 2026-08-08
  page-layout reflow: Songs & Pools (Export Queue left / playlist right),
  Export Registry (Telnet controls left / stat tiles middle / song list
  right), Review & Export (checks + manual starts left / review table
  right).
- The pre-existing full `tests/ui` suite crash (`Windows fatal exception:
  stack overflow`, confirmed unrelated to any of this session's changes via
  `git stash` bisection — see the 2026-08-08 Setlist-drag handoff) is still
  unresolved; run narrower/targeted pytest paths instead of the full
  `tests/ui` directory in the meantime.
