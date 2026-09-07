# Split Video Clip at Playhead + Video Clip Snap

Date: 2026-09-07. Branch: `technical-audit-0815-028d`. Status: complete, needs user manual verification.

## Task objective

Two related Timeline editing capabilities: (A) non-destructive Split of a Video Clip at the
playhead into two clips sharing the same media source, and (B) bringing Video Clip Move/Trim
into the existing Magnet toggle as a target-based snap (Marks, Playhead, other Video Clip
edges, LTC Clip edges). No Ripple, no Insert Gap, no new media files, no second magnet button.

## What was implemented

### Part A — Split (mostly pre-existing; fixed 3 gaps)

Audit found "Split at Playhead" already existed (context-menu action, `split_video_clip_requested`
signal, `MainWindow._split_video_clip` handler) from an earlier session, but with three defects
relative to spec:

1. **Not atomic undo** — it pushed `EditVideoClipsCommand` (shrink original) and
   `AddVideoClipsCommand` (new clip) as two separate undo entries, so a single Undo only
   removed the new clip and needed a second Undo to restore the original's duration. Fixed by
   a new single `SplitVideoClipCommand` (`domain/undo.py`) that shrinks the original and
   adds/removes the new clip together as one entry.
2. **No selection change** — neither clip was selected after split. Per spec v1, the handler
   now calls `timeline.set_selected_video_clip_ids([second.id])` so the **right** (new) clip
   becomes selected — the workflow in the spec relies on this (split at Mark A, then split
   again at Mark B with the still-selected middle piece easy to delete).
3. **Inconsistent minimum-duration boundary** — the split guard allowed a resulting piece as
   short as ~0.02s while every trim elsewhere enforces a 0.05s floor. Unified both the
   context-menu enable check and the handler on 0.05s via a new pure domain function,
   `split_video_clip_transforms()` in `ui/video_clip_edit.py`, mirroring the existing
   `clip_duration_after_right_trim()` pattern (same file, same style, no new constant scheme).

`VideoClip.id` strategy: the clip clicked keeps its **original id** and becomes the LEFT piece
(shrunk in place); the RIGHT piece is a **new id** via `VideoClip.create()` (matches the
existing Duplicate convention). `source_duration_seconds` is now copied onto the new clip
(previously dropped — would have let the new clip's right-trim ignore the source media's real
length).

Split reuses the domain layer's existing minimum-duration convention (0.05s, matching
`_update_video_clip_trim`'s `min_dur`) instead of introducing a second one, per audit instruction.

### Part B — Video Clip Snap (net-new; no such system existed for Video Clips)

Audit found the only existing "Magnet" (`_beat_snap_enabled`, the existing toggle button) only
snaps Marks/LTC-clip drags to **Beat Grid divisions** — there was no target-based snap to Marks,
Playhead, other clip edges, or LTC edges anywhere in the codebase, for any object type. Built
this net-new per spec, reusing the existing toggle (`_beat_snap_enabled`) as the on/off gate
(no second magnet button) and the same 16px-threshold / `_pixels_per_second` conversion pattern
as `_snap_time_to_beat_grid`:

- `_video_clip_snap_targets(exclude_clip_id)` — gathers candidates: Marks (priority 0),
  Playhead (1), other Video Clip start/end excluding self (2), LTC Clip start/end (3).
- `_snap_time_for_video_clip(seconds, exclude_clip_id)` — nearest-candidate-wins within 16px;
  ties (within 1e-9) broken by priority (Mark > Playhead > Video Clip edge > LTC edge), per spec.
- **Move** (`_update_video_clip_drag`): snaps whichever edge (start or end) is closer to a
  target, then repositions `start_seconds` to match — duration and `source_in_seconds` are
  never touched. The existing `clip_start_after_body_drag()` 00:00 hard clamp still applies
  after snapping, so snapping can never reintroduce a negative start.
- **Head trim** (`_update_video_clip_trim`, zone `"left"`): snaps the raw new start time, then
  feeds the resulting delta through the existing clamp chain unchanged (still bounded by
  `min_dur`, `-src_in0`, and `start_seconds >= 0`).
- **Tail trim** (zone `"right"`): snaps the raw new end time, then feeds the resulting delta
  into the existing `clip_duration_after_right_trim()` unchanged (still capped by source length
  and `min_dur`).
- **Magnet OFF**: `_snap_time_for_video_clip` returns the input unchanged when
  `_beat_snap_enabled` is False, so Move/Trim math is byte-for-byte the pre-existing code path.
  Regression test included.
- **Group Move**: intentionally untouched — `_update_group_drag`/`_clamp_group_delta` are a
  separate code path from single-clip Move/Trim and were not touched; existing group-move
  regression tests (`test_marquee_group_move.py`) still pass unmodified.

### Split + Snap interaction

Split uses `self._position` (the actual current playhead time) directly; it does not call the
new snap function, so Magnet being ON never silently moves the split point — matches spec
("Split 本身不要因為 Magnet 開啟而偷偷把 Playhead 改位置").

### Keyboard shortcut `S`

Audited: bare `S` is already a global `QShortcut` on `MainWindow` (`_toggle_setup_shortcut`,
unrelated "Setup" panel toggle). Per spec's collision-avoidance rule, **did not** bind `S` to
Split — kept the existing context-menu-only entry point ("Split at Playhead").

### Waveform cache

No change needed/made. Per audit, the per-clip waveform cache (`VideoClipWaveformCache`) is
already keyed by `(path, mtime, source_in, source_out, duration, media_kind)` — a split's two
resulting clips naturally get independent cache entries without any special-casing, and the
underlying decode is still shared via the media-path-keyed `VideoWaveformArtifact` store. The
Music-lane stand-in waveform dict (`TimelineWidget._artifact_waves`, keyed by clip id) already
walks every eligible clip (fixed in a prior session), so a newly split clip is picked up the
same way any newly added clip is (`_schedule_video_music_standin` is already called after split).

## Files changed

- `src/cueplayer/domain/undo.py` — new `SplitVideoClipCommand`.
- `src/cueplayer/ui/video_clip_edit.py` — new `split_video_clip_transforms()`.
- `src/cueplayer/ui/main_window.py` — `_split_video_clip` rewritten to use the atomic command,
  the shared transform helper, and select the right clip; import updates.
- `src/cueplayer/ui/timeline_widget.py` — new `_video_clip_snap_targets`/`_snap_time_for_video_clip`;
  `_update_video_clip_drag` and `_update_video_clip_trim` now snap when Magnet is on; split
  context-menu enable check unified to the 0.05s boundary.
- `tests/ui/test_video_clip_edit.py` — split domain-math tests (S1, S2, S3 equivalents).
- `tests/domain/test_video_clip_undo.py` — `SplitVideoClipCommand` atomicity test (S6).
- `tests/ui/test_video_clip_split.py` — new file: S3/S4/S5/S6/S7/S8/S9 at the `MainWindow`
  handler level.
- `tests/ui/test_video_clip_snap.py` — new file: N1–N11 (Move/Trim snap to Mark/Playhead/Video
  Clip edge/LTC edge, no self-snap jitter, Magnet OFF regression, threshold boundary, 00:00
  clamp, source_in/duration invariants under snap).

Group Move (N12) is covered by the existing, unmodified `tests/ui/test_marquee_group_move.py`
suite, which still passes — confirms it kept its original clamp/spacing behavior untouched.

## Architecture decisions

- Reused the existing `ClipTransform`/`VideoClipSnapshot` shapes and `_apply`-by-index pattern
  from `EditVideoClipsCommand`/`AddVideoClipsCommand` for the new `SplitVideoClipCommand`,
  rather than inventing a new undo shape.
- Reused the existing Magnet toggle (`_beat_snap_enabled`) and 16px-threshold pattern
  (`_snap_time_to_beat_grid`) for the new Video Clip target-based snap, rather than adding a
  second magnet system or button — the two coexist as separate snap *functions* sharing one
  on/off switch (Beat Grid snap for Marks/LTC-clip-drag against tempo grids; the new
  target-based snap for Video Clip Move/Trim against show anchors). This is a pre-existing
  asymmetry the audit surfaced (Marks/LTC never snapped to Marks/Playhead/clip-edges either,
  only to Beat Grid) — not something this task changed for other object types.
- No new minimum-duration constant: Split now shares the 0.05s floor already used by trim.

## Tests performed

Narrow targeted runs only, per `.ai/NEXT_TASK.md` sandbox guidance (`QT_QPA_PLATFORM=offscreen`,
non-existent media paths, no full `tests/ui` sweep):

```
tests/ui/test_video_clip_edit.py        9 passed
tests/domain/test_video_clip_undo.py    5 passed
tests/ui/test_video_clip_snap.py       11 passed
tests/ui/test_video_clip_split.py       7 passed
tests/ui/test_marquee_group_move.py    (regression, part of the 44-test combined run)
tests/ui/test_video_shift_unlock.py    (regression, part of the 44-test combined run)
Combined regression run: 44 passed, 0 failed
```

No lingering `video_waveform_worker` processes after the run (checked via `tasklist`).

## Remaining issues

- No visual snap-guide/highlight was added (spec allowed skipping if it would grow scope) —
  TODO if the user wants a vertical guide line or target highlight when a Video Clip
  Move/Trim snaps, matching a future Beat Grid-style visual if one exists.
- Needs user manual verification (see checklist below) — not yet exercised in the real app UI.
- Pre-existing test/environment notes from prior sessions (4 baseline UI test failures, several
  hang-prone suites) are unrelated and untouched; see `.ai/NEXT_TASK.md` history.

## Suggested next task

Ripple Edit / Insert Gap / Insert Time (already queued in `.ai/NEXT_TASK.md` from a prior
session) — do not start until the user asks. Otherwise: user manual verification of this task.

## Manual verification steps (for the user)

1. Add a Video Clip, position playhead inside it, right-click → **Split at Playhead** → confirm
   two clips appear, RIGHT one is selected (highlighted).
2. Split again on the new piece → confirm 3 clips total, delete the middle one → confirm the
   two remaining clips are unaffected and still reference the same source file/waveform.
3. Ctrl+Z once after a split → confirm it fully restores the single original clip (not just
   removes the new piece); Ctrl+Shift+Z (or your redo shortcut) → confirm both clips reappear.
4. Turn Magnet ON (existing magnet button) → drag a Video Clip body near a Mark / the Playhead
   / another Video Clip's edge / an LTC Clip's edge → confirm it snaps at ~16px on screen.
5. With Magnet ON, drag a Video Clip's left/right trim handle near the same anchors → confirm
   only that edge snaps and duration/source math still looks correct (compare to Edit Video
   Clip dialog values before/after).
6. Turn Magnet OFF → repeat steps 4–5 → confirm no snapping at all (free positioning, matches
   pre-existing feel).
7. Try dragging a clip so its edge would land within 16px of *itself* (e.g. small back-and-forth
   jiggle) → confirm no jitter/self-snap.
8. Marquee-select multiple objects and group-move them (with Magnet ON or OFF) → confirm group
   move behavior/clamping is unchanged from before this task (no snap applied to group move).
9. Save the project after a split + a magnet-snapped move, reload it → confirm clip positions,
   trims, and IDs are all correct.
