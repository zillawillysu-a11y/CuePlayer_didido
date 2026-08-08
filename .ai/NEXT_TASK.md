# Next task

**Status:** Queued - awaiting manual UI and MA2 export verification
**Type:** MA export workflow UI
**Updated:** 2026-08-08

## Current task

Visually test the compact Songs & Pools layout, Set List → Export Queue
drag/drop, and allocation reports from a real MA2 export. This requires a
human at the desktop app and (for the export check) a real/onPC grandMA2 —
neither is reachable from an automated agent session, so this step is still
pending after the 2026-08-08 code-level verification pass (see
`.ai/handoffs/2026-08-08_ExportQueueClearBugAndRegressionTests.md`).

## Requirements

- Drag one song, a multi-selection, and a Set List folder into Export Queue.
- Drag-reorder within the Export Queue and confirm the new order sticks.
- Click **Clear Queue** and confirm the queue visibly empties (this was
  previously a no-op bug; fixed 2026-08-08 — re-verify in the real UI).
- Confirm queue order is the order shown in Review & Export and in the report.
- Export once and compare `ShowName_Export_Allocation.csv` and `.txt` with the
  actual Sequence, Effect, Group, Timecode, View, and Song Macro Pools.
- Do not touch `startup_error.txt`.
