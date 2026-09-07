# Next task

Next phase (explicitly deferred by the user from this session): **Ripple Edit / Insert
Gap / Insert Time** — auto-pushing later Video Clips, LTC Clips, and Marks to the right
when inserting new content, building on this session's marquee multi-selection + group
move. Do not start until the user asks for it.

Otherwise: waiting on user manual verification of **Split Video Clip at Playhead + Video
Clip Snap** (checklist in `.ai/REPORT.md` / `.ai/handoffs/2026-09-07_VideoClipSplitAndSnap.md`),
the Marquee Multi-Selection + Group
Move feature (checklist in prior `.ai/REPORT.md` history), the Multiple Video Clips Music-lane
stand-in waveform fix (checklist in prior `.ai/REPORT.md` history / its handoff), and separately,
user manual verification (Splash / Main Window title / Help→About dialog / normal
startup) before the next, separate "Release Build" task (run
`packaging\build_windows.ps1` on the Windows build machine and check the built
`CuePlayer.exe` Properties dialog). Do not start Release Build until the user confirms.

**Environment note for future sessions**: do NOT run a full unfiltered `tests/ui/` sweep
in this sandbox — several pre-existing tests spawn a real `video_waveform_worker`
subprocess (by writing bytes to a fake `.mp4` under `tmp_path` and showing a
`TimelineWidget` with Video Track visible) that hangs on garbage input and never
returns, hanging the whole pytest run. Run targeted test files instead; prefer
non-existent video file paths in new Timeline tests unless real decode is specifically
needed (see `.ai/handoffs/2026-09-07_MarqueeMultiSelectGroupMove.md`). Several
already-orphaned instances of that subprocess (hours old, from earlier sessions) were
found and killed with `Stop-Process` during this task — if a Timeline test session in
this sandbox is later found "stuck", check for and kill lingering
`video_waveform_worker` python processes before assuming a real bug.

Candidates parked by user (not started):

- Multi-type Delete (Delete key deleting Video Clips + LTC Clips + Marks together in one
  keypress / one undo entry, for a heterogeneous marquee selection) — explicitly deferred
  this session per instruction; currently Delete only deletes the highest-priority
  selected type (Video Clips > LTC Clips > Marks) when a mixed selection exists, leaving
  the others selected but undeleted (no crash, documented in this session's handoff).
- Ripple Edit / Insert Gap / Insert Time (see "Next phase" above).
- 4 pre-existing baseline test failures found while testing the Multiple Video Clips fix
  (confirmed present with the fix reverted, not caused by it) — investigate only if the
  user asks: `test_video_playhead_jank.py::test_play_uses_coarse_video_wave_and_wider_overscan`,
  `test_mouse_static_backdrop_parity.py::test_video_lane_region_unchanged_on_scrub_press`,
  `test_scrub_fallback_final_land.py::test_fallback_release_finalizes_when_left_button_up`,
  `test_video_standin_cache.py::test_video_standin_restores_from_cache_on_reactivate`.
- `tests/ui/test_video_waveform_backdrop_revision.py` hangs when run without
  `QT_QPA_PLATFORM=offscreen` set (calls `TimelineWidget.show()`, needs a real window in
  this sandbox) — not a bug, just remember to set that env var for this suite.
- Physical loopback 440 Hz + long-capture drift check.
- Pre-existing unrelated failures documented in `.ai/REPORT.md` history (Windows video-sync
  access violation, NDI probe test, `test_song_use_left_ltc.py` routing assertions) — investigate
  only if the user asks; not blocking.
- `tests/ui/test_cue_list_playhead_scroll.py` hangs/crashes the interpreter on Windows when run
  as part of a full `tests/ui` sweep (pre-existing, unrelated to timeline zoom work) — investigate
  only if the user asks.
- `tests/ui/test_timeline_scrub_backdrop_font.py::test_scrub_backdrop_uses_widget_font` fails on a
  pre-existing `TypeError` (test double doesn't accept `include_marks` kwarg added to
  `_paint_static_layers` by a prior task) — confirmed present on baseline `c0bd6ca` before today's
  change, not caused by it; investigate only if the user asks.
- `tests/ui/test_timeline_video_track_controls.py` and `test_transport_main_window_center.py` can
  crash/hang the interpreter under the offscreen Qt test platform due to a pre-existing, unrelated
  non-daemon `webrtc_listen` background thread not shutting down cleanly — investigate only if the
  user asks.

Resolved this session:

- Split Video Clip at Playhead + Video Clip Snap: Split already existed from an earlier
  session (context menu + handler) but had 3 gaps, now fixed — undo/redo is now one atomic
  `SplitVideoClipCommand` entry (was two separate pushes needing two undos), the RIGHT
  (new) clip is now selected after split (was neither), and the split boundary now shares
  the same 0.05s minimum-duration floor as head/tail trim (was a looser, inconsistent
  0.02s). Also built net-new Video Clip Move/Trim snapping onto the existing Magnet toggle
  (`_beat_snap_enabled`) — audit found the only pre-existing snap was Beat-Grid-only for
  Marks/LTC-clip-drag, nothing snapped to Marks/Playhead/clip-edges/LTC-edges before this.
  New `_video_clip_snap_targets`/`_snap_time_for_video_clip` in `timeline_widget.py` give
  Move (body drag) and Trim (head/tail) a 16px-threshold nearest-target snap to Marks >
  Playhead > other Video Clip edges > LTC Clip edges (priority tie-break), reusing the
  existing Magnet button — no second magnet system/button added. Magnet OFF is a full
  bypass (regression-tested); Group Move is untouched (separate code path, its own
  regression suite still passes). `S` was NOT bound as a Split shortcut (already a global
  `_toggle_setup_shortcut` binding) — context-menu "Split at Playhead" remains the only
  entry point. See `.ai/handoffs/2026-09-07_VideoClipSplitAndSnap.md`. Needs user manual
  verification (steps in that handoff).

- Video Clip left-trim-at-00:00 + body-move-past-00:00 hardening: fixed a
  hit-test/hover priority bug where the header-width column splitter (5px
  around `header_width`) silently stole clicks/hover from a Video Clip's
  left trim handle whenever that clip's `start_seconds == 0` (its left edge
  sits exactly on the splitter) — `_hit_video_clip` is now resolved before
  the header/wave splitter checks in both `mousePressEvent` and
  `mouseMoveEvent`. Also, per user decision, removed the old negative
  "pre-roll" feature from `clip_start_after_body_drag()` (was covered by 3
  tests) so a plain **body** drag now hard-clamps at `start_seconds >= 0`
  with no trim/source-offset/duration changes and no jitter; left-trim
  restore-past-a-previous-trim was already correctly clamped at 0 and
  needed no change; multi-select group move was already correctly clamped
  as one shared delta and needed no change. See
  `.ai/handoffs/2026-09-07_VideoClipZeroTrimAndBodyClamp.md`. Needs user
  manual verification (steps in that handoff).

- Release Preflight blocker `tests/ui/test_marquee_over_track_colors.py::test_selection_box_paints_after_mark_track_colors`
  was a stale test, not a production regression. It asserted `_paint_lanes` (which paints
  the mark-track-color lane fills) must be re-invoked on every box-select paint frame. That
  stopped holding once the static backdrop cache (`_blit_scrub_backdrop` /
  `_rebuild_scrub_backdrop`) started serving box-select frames too: on a cache hit, the
  retained pixmap — which already has lanes baked in underneath — is blitted as-is and
  `_paint_lanes` legitimately does not run that frame; `_paint_selection_box` still always
  paints after the blit, so the box-above-track-colors invariant holds regardless. Verified
  by reading `paintEvent`, `_blit_scrub_backdrop`/`_blit_native_backdrop`,
  `_rebuild_scrub_backdrop`, and `_paint_lanes`: the box overlay call is unconditionally
  after both the fresh-bake path (`_paint_static_layers` → `_paint_lanes`, inside
  `_rebuild_scrub_backdrop`) and the cache-hit blit path. No production code changed. Split
  the test into two: one that invalidates the cache first (asserts `_paint_lanes` runs,
  then `_paint_selection_box`) and one with a warm cache (asserts the blit runs, then
  `_paint_selection_box`), so the suite locks the real invariant — overlay-after-background
  — under both cache states instead of one internal helper being called every frame. See
  `.ai/handoffs/2026-09-07_MarqueeTrackColorTestStale.md`.

- About Dialog logo sharpness: the Help → About Cue Player logo looked blurry
  because it loaded the app icon with `QPixmap(path)` (which only reads an
  `.ico`'s first/16x16 frame) then upscaled it 3x to 48x48. Fixed by loading
  via `QIcon(path).pixmap(device_size, device_size)` sized from
  `devicePixelRatioF()`, which lets Qt pick the ico's matching larger layer
  (it has 16/24/32/48/64/128/256px layers) at every DPI scale (100/125/150/
  200%) instead of upscaling. Display size unchanged (48 logical px); menu
  structure, About text, version, copyright untouched. See
  `.ai/handoffs/2026-09-07_AboutDialogLogoSharpnessFix.md`. Needs user manual
  verification across DPI scales (see handoff for steps).

- Marquee Multi-Selection + Group Move: box-select drag across the Video/LTC/Mark lanes
  now selects items of all three types together (previously Mark-only, and selecting one
  type always cleared the others). Dragging any selected item when the combined selection
  includes a clip now moves the whole selected set by one shared, clamped delta (boundary
  clamp uses the group's single earliest item; LTC's overlap-disallowed policy is
  preserved via one deterministic group-wide bound against unselected LTC clips, never a
  per-item re-clamp). One new `GroupMoveCommand` gives the whole move a single undo/redo
  entry. See `.ai/handoffs/2026-09-07_MarqueeMultiSelectGroupMove.md`.

- Multiple Video Clips Music-lane stand-in waveform: a Song with 2+ Video Clips and no
  music audio track only showed the video-audio stand-in waveform over the first clip's
  region. Root cause: `TimelineWidget` held a single `_artifact_wave`/`_artifact_wave_clip`
  pair and `MainWindow` always scheduled the first eligible clip only. Fixed by making
  `TimelineWidget._artifact_waves` a `dict[clip_id, (artifact, clip, complete)]` and
  `MainWindow._schedule_video_music_standin`/`_on_video_standin_finished` walk every
  eligible clip in turn. The Video Track lane's own per-clip waveform was already correct
  for N clips (verified, not the bug). See
  `.ai/handoffs/2026-09-07_MultiVideoClipMusicStandinWaveformFix.md`.

Previously resolved:

- Cue Player 1.14 version / copyright / About integration: single canonical source
  `src/cueplayer/app_info.py` (reads `cueplayer.__version__`) now feeds Splash (new
  low-key "Version 1.14" + copyright footer, existing "Cue Player" title untouched),
  Main Window title ("Cue Player 1.14 — <song>"), a new Help → About dialog, and
  Windows EXE packaging metadata (`packaging/cueplayer.spec` now builds a
  `VSVersionInfo` from `app_info`). `pyproject.toml` version is now `dynamic`,
  reading `cueplayer.__version__`, removing the last duplicate literal. No release
  build was run this session (explicitly deferred). See
  `.ai/handoffs/2026-09-07_VersionCopyrightAboutIntegration.md`.

- Windows title-bar interaction (click / press-hold / drag on the main window or the
  Clean Video Output window) freezing real MTC output during playback. Root cause:
  `AudioEngine._mtc_timer` was a GUI-thread `QTimer` pacing `MtcOutput.tick()` /
  `MidiCueNotes.update()`; Windows suspends all Qt timers on the GUI thread during the
  native title-bar move/resize modal loop. Music audio, audio LTC, and the Playback
  Engine's real position were never affected (PortAudio callback thread, independent of
  Qt); only MTC quarter-frame/MIDI-cue-note output and the (cosmetic) UI TC display /
  video frame refresh stalled. Fixed by replacing `_mtc_timer` with a dedicated daemon
  thread (`_start_mtc_thread`/`_stop_mtc_thread`/`_mtc_thread_loop`) paced by a
  wall-clock `Event.wait(0.004)` instead of a `QTimer`, calling the existing
  `_mtc_tick()` unchanged. See `.ai/handoffs/2026-09-07_MtcTitleBarStallFix.md`.

Previously resolved:

- Zoom-**out** track/lane header labels ("Video" / "LTC Clips" / Mark lane names) temporarily
  going bold during a continuous wheel-zoom-out gesture (the zoom-in case was already fixed in the
  prior task) — root-caused to an unguarded bold-font mutation in `_paint_marks_impl`'s on-waveform
  Cue/Note caption, reached almost every zoom-out tick via `_blit_zoom_preview`'s exact-viewport
  fallback (`_paint_static_layers`), which bypasses the zoom-in fix's `_paint_zoom_screen_annotations`
  guard entirely. Fixed with `save()`/`restore()` around that font mutation plus a defensive font
  reset at the top of `_paint_headers`.

Previously resolved (`758068a` → `c0bd6ca`):

- Initial `clip_generator` LTC Clips lane hydration on project reopen — fixed by making
  `ShowSessionService.refresh_timeline()` push the resolved LTC mode synchronously.
- Zoom-**in** track/lane header label bolding — root-caused to a leaked bold `QFont` on the shared
  zoom-preview `QPainter` in `_paint_zoom_screen_annotations`, fixed with `save()`/`restore()` +
  explicit font resets in `_paint_video_selection_live` / `_paint_ltc_selection_live`.

See `.ai/handoffs/2026-09-07_TimelineZoomOutLabelBoldingFix.md` for the just-completed task,
`.ai/handoffs/2026-09-07_TimelineUiHardeningClipLaneAndZoomFontLeak.md` for the zoom-in +
clip-lane-hydration task, and `.ai/handoffs/2026-09-06_TimelineZoomRenderingHardening.md` for the
one before that.
