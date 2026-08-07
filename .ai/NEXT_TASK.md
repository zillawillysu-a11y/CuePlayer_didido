# Next task

**Status:** Queued — awaiting human start
**Type:** Production MA2 discovery and setup synchronization
**Updated:** 2026-08-08
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

## Current task

Implement read-only Windows MA2 version/output-folder discovery and connect production Registry results to Console Setup using the approved mockup behavior.

## Requirements

- Discover installed `gma2_V_*` folders and the running onPC full executable version.
- Default Output Folder to the selected version's `importexport` folder.
- Provide a native Windows/PySide6 Browse action and a way to restore the version default.
- Preserve a user-selected custom folder across later version changes.
- Synchronize successful Registry results into Sequence, Effects, Timecode, Song Macro, and View starts.
- Do not alter Fixed Macro Start, Template Page, or executors during synchronization.
- Reject versions below 3.3.4.3 and block mismatched/failed results from changing setup.
- Keep Windows discovery in an adapter/service and preserve Unicode path support.
- Do not implement Telnet transport in this task.

## Done when

Focused tests cover version-following/custom folder modes, scan success/failure synchronization, protected fixed settings, unsupported versions, multiple installations, and Unicode paths.
