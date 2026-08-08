# Next task

**Status:** Queued - awaiting manual UI and MA2 export verification
**Type:** MA export workflow UI
**Updated:** 2026-08-08

## Current task

Visually test the compact Songs & Pools layout, Set List → Export Queue
drag/drop, and allocation reports from a real MA2 export.

## Requirements

- Drag one song, a multi-selection, and a Set List folder into Export Queue.
- Confirm queue order is the order shown in Review & Export and in the report.
- Export once and compare `ShowName_Export_Allocation.csv` and `.txt` with the
  actual Sequence, Effect, Group, Timecode, View, and Song Macro Pools.
- Do not touch `startup_error.txt`.
