# Marquee Multi-Selection + Group Move

Date: 2026-09-07. Branch: `technical-audit-0815-028d`. Baseline: `8be59df`. Status: complete
(Phase 1 — Marquee Select + Group Move only; Ripple Edit / Insert Gap is a separate future
phase, per instruction).

## Task objective

Add box/marquee selection over the Timeline's editable area that can select Video Clips,
LTC Clips, and Marks together (not just one type at a time), and let dragging any selected
item move the whole selected group by the same time delta, committed as one undo entry.

## Audit findings (before implementing)

Selection state was three independent `set[str]` fields
(`_selected_clip_ids` / `_selected_ltc_clip_ids` / `_selected_mark_ids`) whose public setters
(`set_selected_video_clip_ids` etc.) actively cleared the *other* two types — only one item
**type** could ever be selected at once. Marquee/box-select already existed but was
Mark-only (`_marks_in_box`, `_box_selecting`/`_box_origin`/`_box_current`/`_box_base_ids`),
gated behind a manual toggle button (`_box_select_mode`) and only reachable over the mark
lanes / scrub zone with Shift. Video Clip and LTC Clip drag state (`_dragging_clip`,
`_dragging_ltc_clip`) were single-id only, while Marks already had a proven multi-item drag
mechanism (`_drag_ids` / `_drag_start_times`, one shared `dt`, one `marks_moved` signal ->
one `MoveMarksCommand`). Undo commands for all three types (`EditVideoClipsCommand`,
`EditLtcClipsCommand`, `MoveMarksCommand`) were already `dict[id -> (before, after)]`
batch-shaped — no new transform types were needed, only a way to apply several types'
worth of them in one undo step. LTC Clips have a real overlap-disallowed/clamp policy
(`_ltc_clamp_start`); Video Clips and Marks have none (Video overlap is visual-only warning;
Marks are point events).

## Implementation

### Selection architecture (`timeline_widget.py`)

Kept the three existing `set[str]` fields as the representation — did **not** introduce a
new heterogeneous selection model, since the fields already support arbitrary members; the
only real blocker was the setters' cross-clearing. Rather than removing that (which would
change plain single-click semantics), the fix targets exactly the two places that need
cross-type coexistence:

1. **Marquee finalize** (`_emit_box_preview`) now computes hits for all three types
   (`_marks_in_box`, new `_video_clips_in_box`, new `_ltc_clips_in_box` — same
   rect-intersects-item-rect rule as the existing Mark one) and writes all three raw sets
   directly, bypassing the exclusive setters. `_begin_box_select` now snapshots/clears all
   three types for additive vs. replace marquees (`_box_base_video_ids` /
   `_box_base_ltc_ids` alongside the existing `_box_base_ids`). On release, all three
   `*_selection_changed` signals are emitted once (previously only `selection_changed` for
   Marks).
2. Marquee is no longer gated behind the `_box_select_mode` toggle for the Video lane, LTC
   lane, or Mark-tracks area — pressing on **empty space** in any of those three lanes and
   dragging starts a marquee (a plain click with no drag still clears the whole selection,
   same effective behavior as before, now via a zero-area box that hits nothing rather than
   a bespoke per-lane clear). The toggle button still exists and its old Shift+scrub-zone
   special case for reading marks while scrubbing is untouched.
3. Marquee hit-tests use `rect.intersects(item_rect)` — Video/LTC clip rects come from
   `_x_for_time(start/end)` × the lane's y-band; Marks keep their existing small
   point-marker rect (`x-6 … x+6`) plus the pre-existing waveform-overlay time-range
   fallback. Nothing in the marquee logic samples raw waveform pixels — only clip/mark
   time ranges — so a marquee crossing the Music waveform never selects "the audio", only
   Marks whose x falls in range (existing behavior, unchanged).

### Group move (`timeline_widget.py`)

New state: `_group_dragging`, `_group_drag_origin_x`, `_group_drag_moved`,
`_group_video_snapshot` / `_group_ltc_snapshot` / `_group_mark_snapshot` (each
`id -> before-transform`, same shapes `EditVideoClipsCommand` / `EditLtcClipsCommand` /
`MoveMarksCommand` already use).

`_group_move_candidate()` — true when the combined selection has more than one item **and**
includes at least one Video/LTC clip. Dragging a selected item's body only enters the new
group-drag path (`_begin_group_drag`) when that's true and no Shift/Ctrl is held; otherwise
it falls through unchanged to the existing single-item `_begin_video_clip_interaction` /
`_begin_ltc_clip_interaction` / `_begin_mark_interaction`. **A marks-only multi-selection
(no clips selected) keeps using the pre-existing `_dragging_marks` mechanism untouched**
(including its beat-grid snap) — this was a deliberate scope-limiting choice to avoid any
regression risk to that already-shipped feature; only selections that include a clip get
the new cross-type group path.

`_update_group_drag` computes one shared `dt` from the drag distance, clamps it once via
`_clamp_group_delta`, then applies the *same* `dt` to every snapshot's stored start time
(never re-deriving per item, so relative spacing is exact by construction). Locked Video
Clips and marks on locked Mark lanes are excluded from the group snapshot entirely (they
don't move, matching single-drag's locked-clip behavior).

`_clamp_group_delta`:
- **Boundary**: `dt = max(dt, -min_start)` where `min_start` is the minimum start time
  across every selected item (not per item) — clamping the whole group at once so relative
  spacing can't be broken by an early item hitting 0 while a later item keeps moving.
- **LTC vs. unselected overlap**: `_clamp_group_delta_for_ltc_overlap` computes one
  `[dt_lo, dt_hi]` bound for the *whole* LTC sub-group by checking each selected LTC clip's
  bounds against every **unselected** LTC clip (ignoring other selected LTC clips — they
  can't newly overlap each other if they didn't already, since the same `dt` is applied to
  all of them) and against the song end. This is the "most conservative, deterministic"
  approach the task asked for instead of per-item re-clamping, which would have broken
  group spacing. Video Clips have no overlap policy (confirmed by audit) so no clamp is
  needed there; Marks have none either.

`_end_group_drag` builds the three per-type change dicts (only entries that actually moved
past a `1e-6` epsilon), sorts each collection that changed, and emits one new signal,
`group_move_committed(video_changes, ltc_changes, mark_changes)`.

### Undo (`domain/undo.py`, `main_window.py`)

New `GroupMoveCommand` dataclass: three optional dicts (`video_changes`, `ltc_changes`,
`mark_changes`, each defaulting to `{}`), `undo()`/`redo()` apply all three in one call
using the *same* field-mutation logic as `EditVideoClipsCommand._apply` /
`EditLtcClipsCommand._apply` / `MoveMarksCommand.undo/redo` (copied inline rather than
reusing those classes' private methods, to keep each command self-contained). It slots into
`SongScopedCommand`/`UndoStack` exactly like every other command (same `undo(song)` /
`redo(song)` / `.label` shape) — **no changes to the undo engine were needed**.
`MainWindow._on_group_move_committed` builds and pushes exactly one `GroupMoveCommand`,
refreshes video-sync/engine/LTC-routing/marks UI as appropriate, and is registered in
`_LTC_COMMAND_TYPES` so undo/redo of a group move that touched any LTC clip still triggers
the existing LTC-specific post-undo refresh (routing, static-layer invalidation).

### Delete — explicitly NOT extended this phase

Per the task's own scope-limiting instruction, multi-type Delete was **not** implemented.
`keyPressEvent`'s existing priority chain (`beat_grid` → `video_clips` → `ltc_clips` →
`marks`, each `return`s on first non-empty match) is unchanged. With cross-type selection
now possible, pressing Delete on a heterogeneous selection (e.g. a Video Clip *and* a Mark
both selected via marquee) will delete **only the Video Clips** and leave the LTC Clips /
Marks selected but undeleted — no crash, no data corruption, just a partial delete. This is
called out explicitly per the instruction rather than silently left ambiguous.

## Files changed

- `src/cueplayer/ui/timeline_widget.py` — marquee generalization, group-drag state machine,
  mousePress/mouseMove/mouseReleaseEvent wiring, new `group_move_committed` signal.
- `src/cueplayer/ui/main_window.py` — `GroupMoveCommand` import, signal connection,
  `_on_group_move_committed` handler, `_LTC_COMMAND_TYPES` registration.
- `src/cueplayer/domain/undo.py` — new `GroupMoveCommand` dataclass; `field` added to the
  `dataclasses` import.
- `tests/ui/test_marquee_group_move.py` — new, 9 regression tests (below).

## Regression tests (`tests/ui/test_marquee_group_move.py`, 9 tests)

A. `test_marquee_selects_across_video_ltc_mark_lanes` — one marquee drag spanning the
   Video/LTC/Mark lanes selects one item of each type.
B. `test_marquee_excludes_items_outside_rectangle` — a far-away Video Clip outside the box
   stays unselected.
C. `test_group_move_applies_same_delta_to_every_selected_item` — +10s group drag moves the
   Video Clip, LTC Clip, and Mark by exactly the same delta; asserts the single
   `group_move_committed` emission carries all three ids.
D. `test_group_move_clamps_at_zero_and_keeps_relative_spacing` — dragging −20s (would go to
   −10s) clamps the whole group to exactly −10s of travel; the Mark's 2s offset from the
   clip is preserved exactly at the clamped position.
E. `test_unselected_item_does_not_move_during_group_drag` — a Mark outside the marquee box
   stays selected-false and stays at its original time after the group drag.
F. `test_undo_once_restores_whole_group` (command-level) + `test_undo_stack_single_entry_for_group_move`
   (through `UndoStack`) — one `undo()` call restores all three types to their pre-move
   state; one `redo()` reapplies all three.
G. `test_single_item_click_drag_still_works_without_regression` and
   `test_single_clip_trim_still_works_without_regression` — a lone selected clip still
   drags/trims itself only (`_group_dragging` stays `False`), no other item moves.

Deliberately used non-existent video file paths (`tmp_path / "a.mp4"` without writing
bytes) in every test — writing real bytes to a fake `.mp4` and then showing the widget
triggers the app's real async video-waveform decode pipeline, which spawns an isolated
`video_waveform_worker` subprocess that hangs on garbage input in this Windows sandbox (see
Baseline findings below). A path that doesn't resolve fails the waveform cache's `stat()`
check harmlessly and no subprocess is ever spawned — selection/group-move logic here never
needs real waveform peaks.

Screenshot/pixel comparison was not used anywhere — all assertions are on selection-id sets,
domain-object time fields, and the emitted signal payload, per the instruction to prefer
selection-model / hit-geometry / group-transform logic over fragile pixel tests.

## Test results

- `tests/ui/test_marquee_group_move.py` — **9 passed** (0.47s).
- `tests/ui/test_mark_ctrl_multiselect.py`, `test_marquee_over_track_colors.py`,
  `test_video_clip_edit.py`, `test_video_select_during_play.py`, `test_beat_grid_selection.py`,
  `tests/domain/test_video_clip_undo.py`, `test_ltc_clip_undo.py`, `test_mark_delete_undo.py`
  — **38 passed, 1 pre-existing baseline failure** (see below).
- `tests/ui/test_video_clip_dialog.py`, `test_timeline_splitter_drag.py`, `test_setlist_undo.py`,
  `test_video_shift_unlock.py`, `test_hide_video_track.py` — **21 passed**.
- `tests/domain/` (full directory) — **166 passed**.
- All runs used `QT_QPA_PLATFORM=offscreen`.

## Baseline findings (NOT caused by this change)

- `tests/ui/test_marquee_over_track_colors.py::test_selection_box_paints_after_mark_track_colors`
  fails identically with this change reverted (confirmed via `git stash` on the three
  changed source files) — pre-existing, unrelated to marquee logic (a `_paint_lanes` paint
  dispatch/order issue, not a selection bug).
- **Important environment finding**: a full, unfiltered `tests/ui/` sweep (145 files) hangs
  this session — not because of this session's changes, but because a number of
  *pre-existing* tests write real bytes to a fake `clip.mp4` inside `tmp_path` and then
  `show()`/paint a `TimelineWidget` with Video Track visible. On this Windows sandbox that
  triggers the real async waveform pipeline (`_use_isolated_waveform_process`), which
  spawns a `video_waveform_worker.exe`-equivalent Python subprocess to decode the garbage
  file; that subprocess never resolves and neither does its parent pytest worker. Several
  such orphaned `video_waveform_worker` processes (dating back hours, from earlier
  unrelated sessions) were found and killed via `Stop-Process` during this task. **Do not
  run a full unfiltered `tests/ui/` sweep in this sandbox** — run targeted files instead,
  and when writing a new Timeline test that references a video/LTC file path, prefer a
  path that does **not** exist on disk (matches the working pattern already used in
  `test_video_select_during_play.py` etc.) unless the test specifically needs real waveform
  decode (in which case mock the decoder as `tests/media/test_video_waveform_artifact.py`
  does).

## Out of scope (per instructions, not touched)

Ripple Edit, Insert Gap / Insert Time, auto-pushing later timeline items right, multi-type
Delete-in-one-keypress, video playback, LTC playback mapping, MTC, waveform rendering, MA
exporter, persistence schema, version/About, Windows title-bar video freeze.
