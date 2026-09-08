# Timeline Video Seek + Cue ID Keyboard Navigation

Date: 2026-09-07. Branch: `technical-audit-0815-028d`. Status: complete, needs user manual verification.

## Task objective

Two small UX-polish items:

- **A. Video Track click-to-seek**: clicking the Video Track (empty space or a clip body)
  moves the playhead to the clicked time, the same way clicking the Music Track already does.
  Dragging a clip body still moves it; dragging an edge still trims it; neither should seek
  continuously while dragging.
- **B. Cue ID Up/Down navigation**: the Cue ID column in the Cue Monitor panel's cue list
  gains the same Up/Down "commit current value, open the adjacent row's editor, stay in edit
  mode" behavior the Note column already has.

Explicitly not touched: Ripple/Insert Gap, Sync Point, Auto Align, Multiple Video Tracks, MTC/LTC,
Split/Snap internals (reused as-is), Playback Engine internals (reused as-is).

## Part A — Video Track seek

### A1/A2 — what changed

`src/cueplayer/ui/timeline_widget.py`:

1. **Empty Video Track area** (`mousePressEvent`, the `elif self._in_video_lane(x, y):`
   branch): this already called `_begin_box_select` for marquee-drag support but never passed
   a `click_seek`. Added `click_seek=self._time_for_x(x)` for the plain-click (no shift/ctrl)
   path — this is the exact same mechanism the waveform's box-select-mode branch a few lines
   below already uses (`click_seek=self._time_for_x(x) if self._in_scrub_zone(x, y) else None`).
   No new seek code path: `_begin_box_select`'s existing release-time logic (`mouseReleaseEvent`,
   `was_box` block) already seeks via `_emit_seek(box_click_seek, input_source="waveform")`
   when the box never grew past 4px — i.e. a real click, not a drag.

2. **Video Clip body click** (`_end_video_clip_gesture`): this function already distinguished
   "clicked, no drag" (`self._clip_drag_moved is False`) from a real move/trim, but only used
   that to skip emitting `video_clip_edited`. Added a `release_x` parameter; when the gesture
   was a body click (not a trim) and never crossed the drag threshold, it now seeks to
   `_time_for_x(release_x)` — the actual clicked time, not `clip.start_seconds` — via the same
   `_emit_seek(..., input_source="waveform")` call the Music Track uses. Selection already
   happened at mouse-press time (`_begin_video_clip_interaction`, pre-existing), so a plain
   click both selects and seeks.

### A3/A4 — click vs. drag, and why release

Reused the project's one existing drag-threshold constant, `self._drag_slop = 10.0`
(`timeline_widget.py:333`) — no new threshold introduced. Both the box-select path and the
clip-gesture path already had "did this exceed the slop" state before this task
(`_clip_drag_moved`, and the box-select release computes `rect.width() >= 4 or height >= 4`);
this task only added a seek call into each existing "it turned out to be a click" branch.

**Seek fires on mouse-release**, matching the pre-existing pattern for marks
(`_drag_click_seek` / `_begin_mark_interaction`, which defers a mark's seek to release for the
identical reason) and for the waveform's box-select-mode click branch. This was a deliberate
choice per the task's A4 requirement: computing "was this a click" requires knowing the whole
gesture, which is only known at release. Seeking at mouse-press would fire on every Move/Trim
gesture too (since press always happens first), which is exactly the "jumps the playhead on
every drag" bug the spec called out to avoid.

### What was NOT changed

- Edge (trim-handle) clicks do not seek, on release or otherwise — only body clicks do (per
  spec A2, which only asks for body-click seek; A3 only asks that edge *drags* not seek).
- `_update_video_clip_drag` / `_update_video_clip_trim` (the live per-move-event functions) are
  untouched — they already only mutate clip geometry, no playhead involvement, before or after
  this change.
- Group Move (`_begin_group_drag`/`_update_group_drag`) is a separate code path entirely and
  was not touched.
- Track Header and every splitter (`_near_header_split`, `_near_wave_split`,
  `_near_video_lane_split`, `_near_mark_lane_split`) are checked in `mousePressEvent` as
  dedicated `elif` branches before the video-lane-background branch is ever reached, so they
  were already excluded from seeking and remain so.
- Marquee (shift/ctrl-held box-select over the video lane) is unaffected: `click_seek` is only
  passed on the plain (non-additive) click path; the `shift or ctrl` branch still calls
  `_begin_box_select(..., additive=True)` with no `click_seek`.
- Magnet (`_beat_snap_enabled`) is unrelated to this click-seek path (it only affects
  `_update_video_clip_drag`/`_update_video_clip_trim`), so ON/OFF cannot change seek behavior.
- Playback Engine / AudioEngine: not touched. `_emit_seek` → `seek_requested` signal →
  `MainWindow._on_timeline_seek_requested` → `_canonical_seek` → `self.playback.seek(...)` is
  the exact same call chain the Music Track already uses; this task added two more call sites
  into that existing chain, no new seek mechanism.

## Part B — Cue ID Up/Down navigation

`src/cueplayer/ui/cue_monitor_panel.py`, in `_PaddedItemDelegate`:

- `eventFilter`'s Up/Down handling previously only matched
  `column == LOGICAL_INDEX_BY_FIELD["note"]`. Widened to
  `column in (LOGICAL_INDEX_BY_FIELD["note"], LOGICAL_INDEX_BY_FIELD["cue_id"])`. Everything
  else in that block (commit-then-close-then-request-navigation) was already column-agnostic.
- The handler (renamed in a comment only — still `_navigate_note_editor`, now documented as
  shared) was already written generically against an `int(column)` parameter and needed no
  logic change to work for Cue ID: it looks up `self.cue_table.item(target, column)`,
  `setCurrentCell`, and `editItem`, all column-agnostic.
- Added one Cue-ID-specific addition inside `_navigate_note_editor`'s `_open_adjacent()`
  closure: after `editItem`, if the column is Cue ID, grab `self.cue_table.focusWidget()` and
  call `.selectAll()` on it (guarded `isinstance(editor, QLineEdit)`). Note's behavior is
  unchanged (no select-all) — the spec explicitly allowed diverging here only if it didn't
  conflict with Note's existing convention, and Note's own editing flow was left untouched.

**Commit-before-navigate**: unchanged mechanism — `self.commitData.emit(editor)` then
`self.closeEditor.emit(editor, NoHint)` fire before `editor_navigation_requested` is emitted;
Qt's item view wires a delegate's `commitData` signal to actually call `setModelData` (which for
Cue ID flows into `_apply_cue_id_edit` via the existing `itemChanged` connection) synchronously,
so the value is persisted before the adjacent editor opens on the next event-loop turn
(`QTimer.singleShot(0, _open_adjacent)`, unchanged).

**Cue ID validation still applies** — same as manual Cue ID edits already did:
`_apply_cue_id_edit` rejects a value that doesn't fit the lane's ascending time-order (via
`main_cue_id_fits_order`) and silently keeps the old value (`cue_id_edit_failed` signal), same
as before this task. Navigating away from a rejected value does not corrupt the row; it simply
doesn't change it, matching pre-existing single-field-edit behavior.

**Boundary**: `_navigate_note_editor`'s existing `max(0, min(rowCount - 1, row + delta))` clamp
already had no-wrap semantics; Cue ID inherits it unchanged. First-row Up / last-row Down
re-opens the same row's editor rather than wrapping or closing.

**Other keys**: only `Qt.Key.Key_Up`/`Key_Down` are intercepted in `eventFilter`; every other
key (Left/Right/Home/End/Backspace/Delete/Enter/Escape/Tab/copy-paste/undo) falls through to
`super().eventFilter(editor, event)` unchanged, for both Note and Cue ID.

## Post-manual-test fix — Cue ID navigation must skip non-Cue-ID rows

Manual testing found the Cue ID Up/Down navigation above used a naive `row + delta` target,
so it stopped on (and opened, uselessly, or bailed silently on) a "Button" row — any Mark row
whose lane has `cue_id_enabled=False` and therefore no Cue ID cell to edit — instead of
continuing past it to the next real Cue ID row, breaking the intended fast-entry workflow
(e.g. `Cue Mark A(101) → Button B → Button C → Cue Mark D(102)`: Down from A should land on D,
not stall on B).

Root cause: `_PaddedItemDelegate.eventFilter` unconditionally called `commitData`/`closeEditor`
*before* checking whether `row + delta` was even a valid Cue ID target — so by the time
`_navigate_note_editor` discovered the single adjacent row wasn't editable and bailed out, the
original editor was already closed, stranding the user's edit position.

Fix, both in `_PaddedItemDelegate` (`cue_monitor_panel.py`):

- New `_find_navigable_row(table, row, column, delta)`: starting from `row + delta`, steps by
  `delta` one row at a time, checking each row's real `item(r, column).flags() &
  Qt.ItemFlag.ItemIsEditable` (the same flag `refresh_list` already sets from
  `lane.cue_id_enabled` — no text/blank heuristic, no new item-type check invented), until it
  finds an editable cell or runs off the end of the table. This reuses the exact editability
  signal the rest of the panel already trusts (e.g. `_on_cell_double_clicked`,
  `_navigate_note_editor`'s own pre-existing editable check).
- `eventFilter` now calls this **before** touching `commitData`/`closeEditor`. If no navigable
  row is found in that direction, it accepts the key event and returns `True` immediately —
  the current editor, its cursor position, and any uncommitted text are left completely
  untouched, and nothing is wrongly committed. Only when a target row is found does it commit,
  close, and emit `editor_navigation_requested` — now carrying the **already-resolved** target
  row with `delta=0` (the delegate did the scanning; the panel side no longer needs to, or can,
  recompute a wrong single-step target).
- `_navigate_note_editor`'s doc comment was updated to state `row` arrives pre-resolved and
  `delta` is always `0` from this call site now; its clamping arithmetic (`row + delta`) still
  works unchanged since `delta` is 0.
- Note column: unaffected in practice. Every Mark row's Note cell is always editable
  regardless of lane, so the scan immediately finds `row + delta` — identical to the previous
  adjacent-row behavior, per the requirement not to change Note's semantics.

No change to: commit-before-navigate mechanism (still fires only once a target is confirmed),
Select-All-on-arrival for Cue ID (unaffected, still applied only after a successful jump),
first/last real-Cue-ID-row boundary semantics (still no wrap — now correctly defined as "no
further *editable* row in that direction", not "no further row at all"), or any other editing
key (Left/Right/Home/End/Backspace/Delete/Enter/Escape/Tab/copy-paste/undo — none of this touches
that code path).

## Files changed

- `src/cueplayer/ui/timeline_widget.py` — video-lane empty-click seek, video-clip body-click
  seek on release.
- `src/cueplayer/ui/cue_monitor_panel.py` — widened Up/Down navigation guard to Cue ID, added
  select-all on Cue ID editor arrival, added `QLineEdit` import; post-manual-test fix added
  `_find_navigable_row` and made `eventFilter` scan-before-commit so navigation skips rows
  whose lane has no Cue ID instead of stalling on them.
- `tests/ui/test_video_track_seek.py` (new) — Task A narrow tests.
- `tests/ui/test_cue_id_navigation.py` (new, later extended) — Task B narrow tests, plus 5 more
  covering skip-a-Button-row, skip-multiple-consecutive-Button-rows, and boundary-with-a-
  trailing/leading-Button-row (editor must survive, not commit garbage, not wrap).

## Tests

Ran narrow/targeted files only (per task instructions — a full `tests/ui/` sweep is known to
hang on fake `.mp4` bytes + `video_waveform_worker`; all new tests use non-existent video paths):

```
tests/ui/test_video_track_seek.py        6 passed
tests/ui/test_cue_id_navigation.py       10 passed (5 added for the skip-non-Cue-ID-row fix)
tests/ui/test_marquee_group_move.py      passed
tests/ui/test_video_clip_snap.py         passed
tests/ui/test_video_clip_split.py        passed
tests/ui/test_video_clip_timeline_zero_trim.py   passed
tests/ui/test_timeline_header_width.py   passed
tests/ui/test_cue_monitor_panel.py       passed
tests/ui/test_timeline_splitter_drag.py  1 failed (test_wave_splitter_drag_defers_geometry_signal)
```

The one failure (`test_wave_splitter_drag_defers_geometry_signal`) was confirmed **pre-existing**
by running the identical file against a `git stash` of this session's changes (fails identically
on baseline commit `23aac87`) — unrelated to this task, not touched by either change here.

New tests cover:
- A1: empty video-lane click seeks to the clicked time.
- A2: clip-body click selects the clip AND seeks to the exact clicked time (not clip start).
- A3/A4: clip-body drag moves without a stray seek; edge trim resizes without a stray seek.
- A5: shift-drag marquee over the video lane does not seek.
- A9: click-seek on a Video Clip feeds Split-at-Playhead a usable time (end-to-end: click →
  seek → `_split_video_clip` splits exactly at the clicked time).
- B1-B3: Down/Up commit the current Cue ID and open the adjacent row's editor, staying in edit
  mode.
- B4: the adjacent editor's Cue ID text arrives fully selected.
- B5/B6: first-row Up and last-row Down do not wrap.
- B8: Note's own Up/Down navigation still works (regression guard for the widened guard).

A6 (Track Header/splitter never seek) and A7 (Magnet on/off doesn't affect click-seek) were
verified by code audit rather than a dedicated test: both are structurally impossible to
violate given the `elif` branch ordering in `mousePressEvent` and the fact that Magnet only
gates `_update_video_clip_drag`/`_update_video_clip_trim`, a disjoint code path from the new
seek calls. A8 (00:00 Move/Trim regression) is covered by the pre-existing
`test_video_clip_timeline_zero_trim.py`, unchanged and still passing.

## Manual verification steps for the user

1. Open a project with a Music Track and a Video Track with at least one clip.
2. Click empty space on the Video Track at various times — confirm the playhead jumps there,
   same as clicking the Music Track waveform does.
3. Click the middle of a Video Clip body (not near either edge) — confirm the clip becomes
   selected AND the playhead jumps to the exact point you clicked (not the clip's start).
4. Press-drag a Video Clip body across the timeline — confirm it moves normally and the
   playhead does NOT chase the drag.
5. Press-drag a Video Clip's left/right edge — confirm it trims normally and the playhead does
   NOT chase the drag.
6. Shift-drag (or plain drag from empty space) a marquee box across Video/LTC/Mark lanes —
   confirm it still multi-selects and does not move the playhead.
7. Drag the header-width splitter and the waveform/video-lane/mark-lane splitters — confirm
   none of them seek.
8. Toggle Magnet on/off and repeat steps 2-3 — confirm click-seek behavior is unaffected either
   way.
9. Click inside a Video Clip at a specific time, then use "Split at Playhead" — confirm it
   splits exactly where you clicked.
10. In the Cue Monitor panel's cue list, click into a Cue ID cell to edit it, type a new value,
    press Down — confirm the value is saved, the next row's Cue ID cell opens in edit mode with
    its text fully selected.
11. Repeat with Up — confirm it goes to the previous row instead.
12. On the first cue mark, press Up while editing Cue ID — confirm it stays put (no wrap to the
    last row). On the last cue mark, press Down — confirm it stays put (no wrap to the first row).
13. Confirm Left/Right/Home/End/Backspace/Delete/Enter/Escape/Tab, copy/paste, and undo still
    work normally while editing a Cue ID.
14. Confirm the Note column's existing Up/Down navigation is unaffected.
15. Set up a lane sequence where a Cue-ID-enabled Mark is followed by one or more marks in a
    lane without Cue ID enabled, then a Cue-ID-enabled Mark again (e.g. Main → Mark 2 → Main).
    Edit the first Cue ID, press Down — confirm it jumps straight to the next Cue-ID-enabled
    row, skipping the row(s) in between, and stays in edit mode with select-all applied.
16. From that later row, press Up — confirm it jumps back to the first row, again skipping the
    non-Cue-ID row(s).
17. On the last Cue-ID-enabled row (with a trailing non-Cue-ID row after it), press Down —
    confirm the editor stays open on the same row with your uncommitted text intact (does not
    jump to the non-Cue-ID row, does not wrap to the first row, does not close/lose the editor).
18. Mirror step 17 with Up on the first Cue-ID-enabled row (with a leading non-Cue-ID row
    before it).
