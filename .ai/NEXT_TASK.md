# Next task

Waiting on user manual verification of the Multiple Video Clips Music-lane stand-in
waveform fix (checklist in `.ai/REPORT.md`), and separately, user manual verification
(Splash / Main Window title / Help→About dialog / normal startup) before the next,
separate "Release Build" task (run `packaging\build_windows.ps1` on the Windows build
machine and check the built `CuePlayer.exe` Properties dialog). Do not start Release
Build until the user confirms.

Candidates parked by user (not started):

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
