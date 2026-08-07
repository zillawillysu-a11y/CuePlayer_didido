# grandMA2 Export Registry Specification

## Purpose

The Export Registry prevents incremental song exports from reusing Pool numbers already present in an MA show.

## Stable identity

- Allocations belong to a stable Song UUID, not Song Order or MA Export Name.
- Reordering or renaming songs never changes an existing allocation.

## Recorded allocation

Each exported song records Sequence range, Effects range, Timecode Pool number, Song Macro number, View number, and export metadata.

## Incremental export

- May include Song Sequences, Timecode, Song Macros, and Song View.
- Song List Sequence is excluded by default.
- Existing allocations are locked.
- New songs may use Auto Allocate or Manual Allocate.
- Auto Allocate starts after the highest registered range or number.
- Manual Allocate is checked against all registered songs.

## Conflicts

- Sequence and Effects use range-overlap validation.
- Timecode, Macro, and View use exact-number validation.
- Conflicts identify the registered song and occupied resource.
- Registration/export is blocked while conflicts remain.

## Lifecycle

- Deleting a playlist song does not automatically release its MA allocation.
- Allocation release is an explicit future action after MA objects are removed.
- Production persistence stores the Registry with the CuePlayer project and backups.
