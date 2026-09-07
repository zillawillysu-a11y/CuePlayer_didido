# Timeline Video Seek + Cue ID Keyboard Navigation

Date: 2026-09-07. Branch: `technical-audit-0815-028d`. Status: complete, needs user manual verification.

## Task objective

Two small UX-polish items on top of the just-completed Split/Snap phase (not modified here):

- **A. Video Track click-to-seek**: clicking the Video Track (empty space, or a clip body)
  moves the playhead to the clicked time, matching the Music Track's existing click-to-seek.
  Dragging a clip body still moves it; dragging an edge still trims it; neither seeks
  continuously mid-drag.
- **B. Cue ID Up/Down navigation**: the Cue ID column in the Cue Monitor cue list gains the
  same Up/Down "commit, open adjacent row's editor, stay in edit mode" behavior the Note
  column already has.

Full detail, code-level reasoning, and files changed: see
`.ai/handoffs/2026-09-07_VideoTrackSeekAndCueIdNav.md`.

## What was implemented

### Part A — Video Track seek (`src/cueplayer/ui/timeline_widget.py`)

- Empty Video Track click now passes `click_seek=self._time_for_x(x)` into the existing
  `_begin_box_select` call (same mechanism the waveform's box-select-mode branch already uses)
  so a plain click (no drag, no shift/ctrl) seeks via the pre-existing box-select release logic.
- Video Clip body click: `_end_video_clip_gesture` gained a `release_x` parameter and now seeks
  to `_time_for_x(release_x)` (the actual clicked point, not `clip.start_seconds`) when the
  gesture never crossed the drag threshold and was a body interaction (not a trim). Selection
  already happened at mouse-press (pre-existing `_begin_video_clip_interaction`), so a plain
  click both selects and seeks in one action.
- No new drag-threshold, no new seek mechanism, no Playback Engine change: reused the existing
  `self._drag_slop = 10.0` constant and the existing `_emit_seek(...) → seek_requested →
  MainWindow._on_timeline_seek_requested → _canonical_seek → playback.seek(...)` chain that the
  Music Track already drives.
- Seek fires **on mouse-release**, matching the pre-existing mark-click pattern
  (`_drag_click_seek`), because "was this a click or a drag" is only knowable once the gesture
  ends; seeking on press would fire on every Move/Trim as well.
- Edge (trim) clicks do not seek (spec only asked for body clicks). Track Header, all four
  splitters, and Group Move are untouched/unaffected — they sit in earlier `elif` branches or a
  fully separate code path. Marquee (shift/ctrl-held drag) never gets `click_seek`. Magnet
  on/off cannot affect click-seek since it only gates `_update_video_clip_drag`/
  `_update_video_clip_trim`.

### Part B — Cue ID navigation (`src/cueplayer/ui/cue_monitor_panel.py`)

- `_PaddedItemDelegate.eventFilter`'s Up/Down handling widened from
  `column == LOGICAL_INDEX_BY_FIELD["note"]` to also match `LOGICAL_INDEX_BY_FIELD["cue_id"]`.
  The commit-then-close-then-request-navigation logic was already column-agnostic.
- The navigation handler (`_navigate_note_editor`) needed no logic change — it already worked
  generically off an `int(column)` parameter — except one addition: after opening the adjacent
  Cue ID editor, it now calls `.selectAll()` on it (guarded to `QLineEdit`). Note's behavior is
  unchanged (no select-all), preserving its existing convention.
- Commit-before-navigate, validation (`main_cue_id_fits_order` rejection of out-of-order
  values), and no-wrap boundary clamping are all pre-existing mechanisms, inherited unchanged.
- Only `Key_Up`/`Key_Down` are intercepted; every other editing key falls through unchanged for
  both columns.

### Post-manual-test fix — Cue ID navigation must skip rows without a Cue ID

Manual testing found Up/Down used a naive `row + delta`, so it stopped dead on any "Button"
row (a Mark whose lane has `cue_id_enabled=False`) instead of continuing to the next real Cue
ID row — and because the delegate already committed/closed the editor before discovering the
target wasn't editable, the user's edit position was lost outright.

Fixed in `_PaddedItemDelegate` (`cue_monitor_panel.py`): new `_find_navigable_row` scans row by
row in the Up/Down direction checking each row's real `ItemIsEditable` flag (the same flag
`refresh_list` already derives from `lane.cue_id_enabled` — no text/blank heuristic), and
`eventFilter` now runs this scan **before** committing/closing anything. If no navigable row
exists in that direction, the key event is consumed and the current editor is left completely
untouched (no commit, no close, no wrong jump); only once a target is found does the existing
commit → close → open-adjacent flow run, now with the already-resolved target row instead of a
single fixed offset. Note column unaffected (every row's Note cell is always editable, so the
scan finds the immediate next row exactly as before).

## Tests

Narrow/targeted files only (a full `tests/ui/` sweep is known to hang on fake `.mp4` bytes +
`video_waveform_worker`; both new test files use non-existent video file paths):

```
tests/ui/test_video_track_seek.py        6 passed  (new)
tests/ui/test_cue_id_navigation.py       10 passed (new; 5 added for the skip-non-Cue-ID-row fix)
tests/ui/test_marquee_group_move.py      passed
tests/ui/test_video_clip_snap.py         passed
tests/ui/test_video_clip_split.py        passed
tests/ui/test_video_clip_timeline_zero_trim.py   passed
tests/ui/test_timeline_header_width.py   passed
tests/ui/test_cue_monitor_panel.py       passed
tests/ui/test_timeline_splitter_drag.py  1 pre-existing failure (unrelated; confirmed also
                                          fails on baseline commit 23aac87 via git stash)
```

## Manual verification needed

See the numbered steps at the end of
`.ai/handoffs/2026-09-07_VideoTrackSeekAndCueIdNav.md`.
