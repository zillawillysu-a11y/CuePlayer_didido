# Next task

**Status:** Queued - awaiting manual UI and MA2 export verification
**Type:** MA export workflow UI
**Updated:** 2026-08-08

## Current task

Visually test the Setlist sidebar → Export Queue drag/drop (the duplicate
in-page Set List tree was removed 2026-08-08; the real left-hand Setlist
panel is now the only drag source), and allocation reports from a real MA2
export. This requires a human at the desktop app and (for the export check)
a real/onPC grandMA2 — neither is reachable from an automated agent session.
See `.ai/handoffs/2026-08-08_DragFromRealSetlistIntoExportQueue.md`.

## Requirements

- Drag one song from the Setlist sidebar into the Export Queue.
- Multi-select several songs in the Setlist and drag them in together.
- Drag a whole Setlist folder into the Export Queue (queues every song in
  it, in order).
- Drag-reorder within the Export Queue and confirm the new order sticks.
- Click **Clear Queue** and confirm the queue visibly empties (fixed
  2026-08-08 — was previously a no-op; re-verify in the real UI).
- Confirm queue order is the order shown in Review & Export and in the report.
- Export once and compare `ShowName_Export_Allocation.csv` and `.txt` with the
  actual Sequence, Effect, Group, Timecode, View, and Song Macro Pools.
- Do not touch `startup_error.txt`.

## Separately (not blocking, lower priority)

The full `tests/ui` pytest suite crashes with `Windows fatal exception:
stack overflow` partway through when run all together in one process
(pre-existing, confirmed unrelated to 2026-08-08 changes via `git stash`
bisection). Likely thread/resource accumulation across hundreds of
`MainWindow()` instantiations in one process. Worth its own investigation;
run narrower/targeted pytest paths in the meantime rather than the full
`tests/ui` directory.
