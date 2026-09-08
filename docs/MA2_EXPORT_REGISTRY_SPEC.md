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

## Live scan transport

- CuePlayer sends login and scanner commands through Telnet TCP port 30000.
- CuePlayer may receive framed scanner output through the read-only System Monitor TCP port 30001.
- Scanner records include MA2 version and use an unambiguous CuePlayer prefix/begin/end frame.
- A snapshot-file import remains the offline fallback.
- The scanner must support grandMA2 3.3.4.3 through the latest verified 3.9 profile.

## Console Setup synchronization

- Installed/running-version detection updates only the Console target and its version-following output folder.
- A successful live show scan applies the Registry's next conflict-free Sequence, Effects, Timecode, Song Macro, and View starts to Console Setup.
- Fixed Macro Start, Template Page, executors, and other fixed control settings are preserved unless the user changes them.
- Console Setup identifies Registry scanning as the source and shows the host, remote version, and applied starts.
- A failed, unsupported, or version-mismatched scan must not change Console Setup.
