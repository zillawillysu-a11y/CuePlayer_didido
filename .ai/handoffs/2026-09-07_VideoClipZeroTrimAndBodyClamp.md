# Video Clip: left-trim hit area at timeline 0 + body-move clamp at 0

## Problem 1 — could not grab the left trim handle when a clip starts at 00:00

Root cause was **hit-test priority order in `mousePressEvent`**, not the trim
hit-zone width. `TimelineWidget._hit_video_clip()` already used a small
(`_clip_edge_hit = 8.0` logical px) symmetric window around each edge, and
`_in_video_lane()` already excludes `x < self._header_width`, so at
`start_seconds == 0` (`x0 == header_width`) the *effectively reachable* part
of that window was already only the 8px **inside** the clip (`x0..x0+8`) —
correct in principle.

The actual bug: `mousePressEvent` checked `self._near_header_split(x)`
(`abs(x - header_width) <= 5px`, the draggable Track-Header/Timeline column
splitter) **before** `self._hit_video_clip(...)`. Since a clip starting at 0
has its left edge exactly on the header splitter, the splitter's 5px hit
zone silently stole every click in `[header_width, header_width+5]` — the
same region the left trim handle needed — so the user was resizing the
header column instead of trimming.

`mouseMoveEvent`'s hover-cursor logic had the identical ordering bug
(`hover_header` computed before `pre_clip`), so the cursor never even showed
`SizeHorCursor` for the trim handle in that zone.

### Fix

In both `mousePressEvent` and `mouseMoveEvent` (`src/cueplayer/ui/timeline_widget.py`),
`_hit_video_clip(...)` is now resolved **first**; the header-split and
wave-split splitters only get a chance when no clip (body or edge) was hit
at that point. This is a pure re-order — no new hit-zone constants, no
`_clip_edge_hit` width change. Elsewhere (any clip not sitting on the
splitter, or no clip at all) behavior is unchanged, since `_hit_video_clip`
returns `None` outside the Video lane / off any clip. Verified
`test_video_select_during_play.py::test_press_prefers_clip_over_video_lane_splitter`
(pre-existing, unrelated splitter-priority test) still passes.

Right-trim was already effectively fine (its edge is almost never pinned to
the header splitter), so no change was needed there — behavior is now
consistent left/right by construction since both go through the same
`_hit_video_clip` call.

## Problem 2 — dragging the clip body left of 00:00

`clip_start_after_body_drag()` (`src/cueplayer/ui/video_clip_edit.py`) used
to be a deliberate **pre-roll** feature: clips could be dragged to a
negative `start_seconds` (soft-snap-at-zero, escapable by dragging past a
0.12s well, `min_start_seconds = -600.0`), covered by 5 existing tests in
`tests/ui/test_video_clip_edit.py`.

This directly conflicted with this task's requirement ("body move must never
go negative — hard clamp at 0, no ripple/trim/offset changes"). **Asked the
user**; they chose to remove pre-roll entirely rather than add a second
code path. `clip_start_after_body_drag()` is now:

```python
def clip_start_after_body_drag(start0: float, dt_seconds: float) -> float:
    return max(0.0, start0 + dt_seconds)
```

The `snap`/`snap_seconds`/`min_start_seconds` parameters and the whole
snap-well logic are gone; call sites in `timeline_widget.py`
(`_update_video_clip_drag`, `_nudge_video_clips`) and `main_window.py`
(3 call sites, all pass `dt_seconds=0.0` for post-paste/append clamping —
unaffected) were updated accordingly. `_update_video_clip_drag` no longer
takes a `snap` kwarg; its one caller in `mouseMoveEvent` no longer computes
an unused `shift` local for it.

Left-trim (`_update_video_clip_trim`, zone == "left") was **already**
correct and untouched: `delta = min(max(dt, -start0), dur0 - min_dur)` then
`delta = max(delta, -src_in0)` — this already caps head-trim-restore
exactly at timeline 0 and at the source's own start, so a previously
trimmed clip can restore media leftward but never past 0 or into negative
source offset (test C, below).

Multi-select **group** move (`_clamp_group_delta` /
`_update_group_drag`) already clamped the whole group by one shared delta
using the group's single earliest `start_seconds`, preserving relative
spacing — this was already correct per the marquee-multi-select group-move
work from earlier this session and was **not** changed. Verified with a new
regression test (F below) and by re-running
`tests/ui/test_marquee_group_move.py` (all pass).

## Files changed

- `src/cueplayer/ui/timeline_widget.py` — hit-test/hover priority re-order
  (clip before header/wave splitter) in `mousePressEvent` and
  `mouseMoveEvent`; dropped the now-unused `snap` kwarg plumbing on
  `_update_video_clip_drag`.
- `src/cueplayer/ui/video_clip_edit.py` — `clip_start_after_body_drag()`
  simplified to a hard `max(0.0, start0 + dt_seconds)` clamp; pre-roll /
  soft-snap logic removed (user-approved breaking change).
- `tests/ui/test_video_clip_edit.py` — replaced the 3 pre-roll-specific
  tests with one `test_body_drag_clamps_at_zero_no_pre_roll`; kept the
  unrelated `test_long_clip_can_move_past_song_end` and the right-trim /
  default-duration tests as-is.
- `tests/ui/test_video_clip_timeline_zero_trim.py` — **new**, 6 focused
  tests (A–F from the task spec), using a nonexistent media path
  (`Z:/nonexistent/does-not-exist*.mp4`) so no real decode/waveform-worker
  subprocess is ever spawned.

## Tests

Ran targeted files only (per this project's standing note: never run a full
unfiltered `tests/ui/` sweep — some pre-existing tests spawn a real
`video_waveform_worker` subprocess against garbage `.mp4` bytes and hang):

- `tests/ui/test_video_clip_timeline_zero_trim.py` — 6 passed (new)
- `tests/ui/test_video_clip_edit.py` — 5 passed (1 rewritten)
- `tests/ui/test_ltc_clip_timeline.py` — 12 passed (unrelated lane, sanity check same file)
- `tests/ui/test_marquee_group_move.py` — passed (group-move regression, untouched code path)
- `tests/ui/test_hide_video_track.py`, `test_timeline_video_track_controls.py`,
  `test_video_shift_unlock.py`, `test_video_select_during_play.py` — all passed
  (42 total across this batch, including the splitter-priority test above)

`python -m cueplayer.ui.main_window` import sanity-checked (no syntax/reference
errors from removing the `snap` kwarg). `git diff --check` clean (only a
benign CRLF-normalization note from git, no whitespace errors).

## Manual verification steps for the user

1. Open a Song, add/drag a Video Clip so its left edge sits exactly at 00:00.
2. Hover the mouse just inside the clip's left edge (a few px right of
   00:00) — cursor should show the horizontal resize (↔) cursor, and the
   header-width column splitter should *not* activate.
3. Drag right from there — clip should trim (head-trim: start increases,
   duration shrinks, source in-point advances). The Track Header column
   width must not change during this drag.
4. If that clip was previously head-trimmed, grab its left trim handle and
   drag left — media should restore up to, but never past, 00:00 (clip
   can't go negative, source offset can't go negative).
5. Select a clip's **body** (not an edge) starting away from 0 (e.g. 10s)
   and drag it left past 00:00 — it should stop exactly at 0 with duration
   and source offset unchanged (no auto-trim). Continue dragging further
   left — clip should stay pinned at 0 with no jitter.
6. Marquee-select 2+ Video Clips (including one near 0) and drag the group
   left past 0 — the whole group should stop together with relative spacing
   preserved (not just the earliest clip clamped independently).
