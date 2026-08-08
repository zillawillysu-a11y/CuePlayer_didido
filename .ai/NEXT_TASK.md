# Next task

**Status:** Queued - awaiting manual UI and MA2 export verification
**Type:** MA export workflow UI
**Updated:** 2026-08-08

## Current task

Manually verify, in the running desktop app, everything implemented across
the 2026-08-08 sessions (see the day's handoffs in `.ai/handoffs/`):

1. **Per-song manual Pool overrides** (`.ai/handoffs/2026-08-08_PerSongManualPoolOverrides.md`):
   - Double-click a Sequence/Effects/Groups/Timecode/View/Song Macro cell in
     the Review & Export table — confirm it becomes editable and the typed
     number sticks (re-check after switching tabs / re-opening the page).
   - Force a collision (type the same number for two songs in the same Pool
     column) — confirm red highlight + tooltip appears.
   - Try **Auto-Fill & Sequence** (seed the 6 fields, click it, confirm
     every song in the queue gets sequential numbers) and **Clear All
     Overrides**.
   - Do one real MA2 export with at least one override active. Confirm the
     console actually imports the overridden song at the typed Pool number
     for Sequence/Timecode/View. If a Song Macro override was used, check
     the generated `.lua` — it should show several `Import ... At Macro N`
     lines (one per song) instead of the usual single combined import.
   - Remember: **Groups overrides are planning/report-only** — the exporter
     has no real Group Pool object-creation path yet, so don't expect the
     console to actually have Groups created there.

2. **Page layout reflow** (`.ai/handoffs/2026-08-08_ConsoleSetupUiFixesAndPageLayoutReflow.md`,
   width fix in `.ai/handoffs/2026-08-08_RegistryAndReviewLayoutWidthFix.md`):
   Songs & Pools (Export Queue left / playlist right), Export Registry
   (Telnet controls left, capped ~360px / stat tiles middle, capped ~200px /
   song list right, fully visible), Review & Export (checks + manual starts
   left, capped ~340px / review table right) — confirm the Song List and
   review table are now fully visible (not cut off) and the Manual Pool
   Starts fields no longer overlap their labels.

3. **View Layout "Follow Console Setup" checkbox** — confirm checking it
   syncs Pool Start live from Console Setup and updates when switching
   Preview Song; confirm unchecking it keeps the View Layout's own
   independent number.

4. **Setlist sidebar drag into Export Queue** (`.ai/handoffs/2026-08-08_DragFromRealSetlistIntoExportQueue.md`):
   drag one song / a multi-selection / a whole folder from the real Setlist
   sidebar into the Export Queue; drag-reorder within the queue; click
   **Clear Queue** and confirm it now visibly empties.

## Also pending (not blocking)

The pre-existing full `tests/ui` pytest suite crashes with `Windows fatal
exception: stack overflow` partway through when run all together in one
process (confirmed unrelated to any of this week's changes via `git stash`
bisection). Likely thread/resource accumulation across hundreds of
`MainWindow()` instantiations in one pytest process. Worth its own
investigation; run narrower/targeted pytest paths in the meantime rather
than the full `tests/ui` directory.
