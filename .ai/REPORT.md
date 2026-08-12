# Latest AI task report

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Make left-click Add Mark from Mark Track headers an opt-in safety switch,
defaulting off and configurable from the header context menu.

## What was implemented

- Added project-global `mark_lane_header_add_enabled`, default `False`.
- Left-clicking a Mark Track name emits Add Mark only when enabled.
- Right-clicking any Mark Track name now shows a checkable
  `Click Track Header to Add Mark` action.
- Disabled mode no longer shows the pointing-hand add affordance over headers.
- Toggle changes mark the project dirty, show status feedback, and persist in
  project JSON.
- Legacy projects without the field load safely with the feature off.

## Files changed

- `src/cueplayer/domain/models.py`
- `src/cueplayer/persistence/project_store.py`
- `src/cueplayer/ui/timeline_widget.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_mark_lane_rename.py`
- `tests/persistence/test_mark_lane_header_add.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-12_MarkTrackHeaderAddSwitch.md`
- `.ai/NEXT_TASK.md`

## Architecture decisions

- This is project/show behavior, not a machine preference or per-lane flag.
- Mark creation remains routed through the existing `add_mark_requested` signal.
- Playback clock and Mark undo behavior are unchanged.

## Tests performed

- Header click behavior plus project persistence compatibility: 9 passed.

## Remaining issues

- User should validate right-click toggle wording and behavior in the real UI.

## Suggested next task

Confirm header clicks do nothing by default, enable the right-click switch and
confirm they add Marks, then package and smoke-test CuePlayer 1.1.3.
