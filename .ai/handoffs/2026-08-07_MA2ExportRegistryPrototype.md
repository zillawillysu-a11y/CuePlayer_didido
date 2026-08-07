# MA2 Export Registry Prototype

## Task objective

Prototype a Registry that shows occupied MA resources and safely allocates incremental exports without Song List updates.

## What was implemented

- Added an Export Registry workflow page.
- Added Existing/Pending rows for Sequence, Effects, Timecode, Macro, and View.
- Added next-available summaries, Auto Allocate, Manual Allocate, and conflict details.
- Added in-prototype Register Export behavior.
- Incremental components exclude Song List Sequence.
- Added stable Song IDs and keyed allocations by those IDs.
- Existing allocations survive Song Order and MA Export Name changes.
- Connected View Layout previews to registered or pending allocations.
- Added `docs/MA2_EXPORT_REGISTRY_SPEC.md`.

## Files changed

- `design/ma_export_playlist_mockup.html`
- `docs/MA2_EXPORT_REGISTRY_SPEC.md`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-07_MA2ExportRegistryPrototype.md`

## Architecture decisions

- Allocation ownership uses stable Song UUID, never order or mutable names.
- Sequence/Effects conflicts compare ranges; Timecode/Macro/View compare exact values.
- Existing allocation release is not automatic.
- The prototype Registry is memory-only; production must persist it with project data.

## Tests performed

- Parsed embedded JavaScript with Node.
- Verified Registry controls, behaviors, and unique HTML IDs.
- Verified View preview routing uses the song allocation function.
- Ran `git diff --check`.

## Remaining issues

- User review of Registry density and Manual Allocate interaction is required.
- Production persistence schema/migration is not implemented.
- Register Existing and explicit Release Allocation remain future work.
- Zero-content song behavior remains undecided.

## Suggested next task

Review the Registry and new-song allocation interaction, then define zero-content behavior and production persistence requirements.
