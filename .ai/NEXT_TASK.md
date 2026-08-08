# Next task

**Status:** Queued - awaiting manual UI and real-MA2 verification
**Type:** MA export workflow UI
**Updated:** 2026-08-08

## Newest item (2026-08-08, do this first)

Verify the MA2 Exporter close-out round — see
`.ai/handoffs/2026-08-08_PageAllocationCsvSaveAsAndReviewLayoutCloseout.md`:

1. Open Review & Export in the desktop app: confirm the page no longer
   scrolls as a whole (only the right-side table scrolls), the left-side
   controls are fully visible, and "Start after scanned Pools" no longer has
   a mismatched dark background bar (Export Registry too).
2. Run **Write Scanner Plugin** → **Install & Scan** once against a real
   MA2 console. Confirm "Show scan max IDs" now includes a **Page** number.
   If it stays "—", `gma.show.getobj.handle('Page ' .. n)` may not be a
   valid handle kind on your MA2 firmware — flag this back, since it could
   not be verified from this environment.
3. Tick **Start after scanned Pools** and confirm songs' **Page** numbers
   move past the scanned max, same as the other six Pool types already do.
4. On Review & Export / Export Registry / Songs & Pools, confirm every table
   now shows a **Page** column (between View and Song Macro) and the numbers
   match across all three tables and the real export.
5. Click **Export Allocation Report (CSV)…** on Review & Export (new button
   next to Refresh Patch). Confirm:
   - The Save As dialog opens at the folder containing the current
     CuePlayer Project file (or a Documents-style folder if the project has
     never been saved) — **not** the MA2 import/export folder.
   - The default filename is reasonable and editable.
   - The saved CSV has columns: Order, Song, Export Name, Sequence, Effects,
     Groups, Timecode, View, Page, Song Macro — "Song" is the real song
     title, "Export Name" is the sanitized MA export name (previously the
     CSV only had one name column, and it was actually the Export Name).
   - After saving, the app tells you the exact path.
6. Do one real MA2 export with a manual **Page** override on one song;
   confirm on the console that its Main/Buttons land on the typed Page.
7. Songs_Pools table header now reads "Export Name" (was "MA Export Name")
   — label only, confirm nothing else changed about that column's data.

## Also pending (not blocking)

The pre-existing full `tests/ui` pytest suite crashes with `Windows fatal
exception: stack overflow` partway through when run all together in one
process (confirmed unrelated to this week's changes via `git stash`
bisection earlier). Run narrower/targeted pytest paths instead of the full
`tests/ui` directory.

## Explicitly not touched this round (per instruction)

- Groups allocation / creation / import logic — already verified PASS on
  real MA2 hardware; left exactly as-is.
- video-waveform code — out of scope, not touched.
