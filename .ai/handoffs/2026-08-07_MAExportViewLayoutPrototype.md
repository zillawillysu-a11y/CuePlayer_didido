# MA Export View Layout Prototype

## Task objective

Add an interactive MA-like Screen 3 View editor to the existing MA Export browser mockup.

## What was implemented

- Added a new `View Layout` workflow page before Review & Export.
- Added a scalable 16:9 Screen 3 canvas with grid lines.
- Added default Sequence, Group, Effect, and Template Effect Pool windows.
- Pool windows support selection, pointer dragging, and lower-right resizing.
- Added optional 5% × 10% grid snapping and layout locking.
- Added a Pool Inspector for type, X, Y, width, height, Pool start, and visible slots.
- Added Pool creation, duplication, deletion, and default-layout reset.
- Added song preview selection; Sequence and Effect ranges update from each song's allocation.
- Added an Apply Template to All Songs prototype action.

## Files changed

- `design/ma_export_playlist_mockup.html`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-07_MAExportViewLayoutPrototype.md`

## Architecture decisions

- This remains a browser-only interaction prototype; PySide6 and MA2 XML output are unchanged.
- Geometry uses percentages relative to a 16:9 canvas for responsive preview.
- One template is shared across songs; song preview substitutes calculated Sequence and Effect Pool starts.
- Production must translate editor geometry to verified MA2 Screen 3 View XML coordinates.

## Tests performed

- Parsed embedded JavaScript with Node `new Function`.
- Verified required editor controls and behavior functions exist.
- Verified HTML IDs are unique.
- Ran `git diff --check`.

## Remaining issues

- The user needs to review interaction and visual fidelity against grandMA2.
- Decide whether song-specific layout overrides are required in the first implementation.
- Persistence format and MA2 View XML coordinate conversion remain to be designed.
- Zero-content song export behavior remains undecided.

## Suggested next task

Review the View Layout prototype, decide shared-template versus per-song override scope, and define zero-content song behavior before production implementation.
