# Marquee Multi-Selection + Group Move (Phase 1)

Date: 2026-09-07. Branch: `technical-audit-0815-028d`. Baseline: `8be59df`. Status: complete.

## Task objective

Add marquee/box selection across Video Clips, LTC Clips, and Marks in one drag, and group
move for the selected set with one shared delta and one undo entry. Ripple Edit / Insert
Gap is an explicitly separate future phase.

## What changed

- Selection (`timeline_widget.py`): the three existing per-type `set[str]` selection fields
  now coexist (marquee finalize writes all three directly instead of going through the
  mutually-exclusive setters). Marquee hit-testing generalized from Mark-only
  (`_marks_in_box`) to also cover Video Clips (`_video_clips_in_box`, new) and LTC Clips
  (`_ltc_clips_in_box`, new) using the same rect-intersects-item-rect rule, and is now
  reachable from empty-space drags in the Video lane, LTC lane, and Mark tracks (previously
  gated behind a manual toggle + Mark-tracks/scrub-zone only).
- Group move (`timeline_widget.py`): dragging any selected item when the combined selection
  spans more than one item and includes a clip now moves the *whole* selection by one
  shared, clamped `dt` (`_begin_group_drag`/`_update_group_drag`/`_end_group_drag`). Boundary
  clamp uses the group's single earliest start time (not per item). LTC's existing
  overlap-disallowed policy is preserved via one deterministic delta-bound computed against
  unselected LTC clips only — never a per-item re-clamp, so relative spacing survives
  exactly. A marks-only multi-selection still uses the pre-existing, unmodified
  `_dragging_marks` path (zero regression risk to that already-shipped feature).
- Undo (`domain/undo.py`, `main_window.py`): new `GroupMoveCommand` (three optional
  `id -> (old, new)` dicts, one per type) — slots into the existing `SongScopedCommand`/
  `UndoStack` machinery unchanged. One `group_move_committed` signal → one command push.
- Delete was **intentionally not extended** to multi-type in this phase (see handoff for
  the exact, documented, non-crashing partial-delete behavior when this comes up).
- Full detail, per-symbol rationale, and the LTC clamp math: see
  `.ai/handoffs/2026-09-07_MarqueeMultiSelectGroupMove.md`.

## Files changed

- `src/cueplayer/ui/timeline_widget.py`
- `src/cueplayer/ui/main_window.py`
- `src/cueplayer/domain/undo.py`
- `tests/ui/test_marquee_group_move.py` (new, 9 tests)

## Test results

- New file: 9/9 passed.
- Targeted existing suites re-run (selection, undo, video/LTC clip editing, splitters,
  setlist undo, all of `tests/domain/`): 38 + 21 + 166 = 225 passed, 1 pre-existing
  baseline failure (`test_marquee_over_track_colors.py`, confirmed present with this
  change reverted — unrelated paint-order issue, not a selection bug).

## Important environment note for future sessions

**Do not run a full, unfiltered `tests/ui/` sweep in this sandbox.** A number of
pre-existing tests write real bytes to a fake `clip.mp4` under `tmp_path` and then
`show()` a `TimelineWidget` with the Video Track visible; on this Windows sandbox that
triggers a real async waveform-decode subprocess (`video_waveform_worker`) that hangs on
garbage input and never returns, hanging the whole pytest run along with it. Several
orphaned instances of that subprocess (from earlier, unrelated sessions, running for
hours) were found and killed with `Stop-Process` during this task. Always run targeted
test files instead, and when a new Timeline test references a video/LTC file path, prefer
one that does **not** exist on disk (as most existing passing tests already do) unless the
test specifically needs real decode, in which case mock the decoder the way
`tests/media/test_video_waveform_artifact.py` does.

## Manual verification checklist for the user

1. Timeline has a Video Clip, an LTC Clip (clip_generator mode), and a Mark roughly
   aligned in time. Drag a marquee from above the Video lane down through the LTC and Mark
   lanes, covering all three — confirm all three highlight as selected.
2. Drag any one of the three selected items — confirm all three move together by the same
   amount, keeping their relative spacing.
3. Drag the group left until the earliest item would go negative — confirm the whole group
   stops together at the boundary (0s), not one item stopping while others keep moving.
4. With an LTC Clip in the selected group and another LTC Clip nearby but not selected,
   drag the group toward the unselected clip — confirm the group stops before overlapping
   it (LTC's existing no-overlap rule still holds for the group as a whole).
5. Press Ctrl+Z once after a group move — confirm all items return to their original
   positions in one step (not one Undo per item). Ctrl+Shift+Z (or your Redo shortcut)
   reapplies the whole move in one step.
6. Click a single Video Clip (no marquee) and drag/trim it — confirm it behaves exactly as
   before (only itself moves/trims, nothing group-related).
7. Marquee-select only Marks (no clips) and drag one — confirm the existing marks-only
   multi-drag behavior (including beat-grid snap, if enabled) is unchanged.
