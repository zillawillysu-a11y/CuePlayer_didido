# Windows title-bar interaction freezing real MTC output (GUI-QTimer scheduling bug)

Date: 2026-09-07. Branch: `technical-audit-0815-028d`. Baseline: `9e899ff`. Status: complete.

## Task objective

Manual testing found that while CuePlayer is playing and outputting Timecode, clicking,
press-holding, or dragging the Windows title bar of the main window or the Clean Video
Output window would break/stall Timecode output. Diagnose which of Music audio, LTC
audio, MTC, UI Timecode display, Playback Engine position, and Video playback/sync are
actually affected — distinguishing a real Timecode-output interruption from a mere UI
display freeze — then fix only what is actually broken with a minimal, safe change,
without redesigning the Playback Engine or touching LTC Clip mapping / Timeline UI /
exporters / persistence / waveform / NDI / video_sync.

## Diagnosis

Audited `src/cueplayer/playback/audio_engine.py`, `src/cueplayer/playback/mtc_output.py`,
`src/cueplayer/playback/midi_cue_notes.py`.

- **Music audio** and **audio LTC**: both rendered inside `AudioEngine`'s PortAudio
  stream callback (`_make_stream_callback`, `sd.OutputStream`'s own native callback
  thread), which also advances `_position_frame` — the Playback Engine's actual sample
  clock — under `self._lock`. This thread is independent of Qt entirely. **Not
  affected** by a Windows title-bar modal loop.
- **Playback Engine position**: advanced from the same PortAudio callback thread (real
  playback) or from `_silent_tick` (a GUI `QTimer`, used only when no output stream is
  needed at all). For any song with audible output, the real clock is audio-thread-driven
  and **not affected**.
- **MTC — was affected, and this is the actual bug.** `AudioEngine.__init__` built
  `self._mtc_timer = QTimer(self)` (4 ms interval) wired to `self._mtc_tick`, which calls
  `MtcOutput.tick()` (quarter-frame pacing) and `MidiCueNotes.update()` (Main/Button MIDI
  cue notes). A `QTimer` only fires from inside its thread's Qt event loop. On Windows,
  dragging or press-holding a top-level window's title bar makes `DefWindowProc` enter a
  native, blocking `WM_SYSCOMMAND`/`WM_NCLBUTTONDOWN` modal move/resize loop **on the GUI
  thread**, which pumps only its own internal message loop and does not return control to
  Qt's event loop until the interaction ends. All Qt timers on that thread — including
  `_mtc_timer` — stop firing for the entire duration of the drag, on every top-level
  window in the process (one shared GUI thread), so both the main window and the Clean
  Video Output window's title bars trigger it. Real MTC quarter frames (and Main/Button
  MIDI cue notes) stopped being sent for as long as the drag lasted, even though audio
  kept playing correctly.
- **UI Timecode display** and **video frame refresh**: also driven by GUI `QTimer`s
  (`_poll` at 16 ms for `position_changed`; the video window's own repaint / timer path)
  and by Qt paint events, so they also stall during the drag — but this is cosmetic
  display freeze, matching normal Windows behavior for *any* Qt app during a native
  title-bar interaction, not a "wrong output" bug. Audio and the Playback Engine clock
  underneath were never wrong; the display simply didn't repaint until the drag ended,
  and then it caught up to the (correct, unaffected) real position on the next tick — no
  burst, no backlog. **Not required to be fixed** per the diagnosis, and left untouched.

Root cause, precisely: `AudioEngine._mtc_timer` (a Qt `QTimer` on the GUI thread) was the
sole pacing source for `MtcOutput.tick()` / `MidiCueNotes.update()`, so real MTC output
depended on the Qt GUI event loop continuing to pump — which Windows explicitly suspends
during a native title-bar move/resize modal loop.

## Fix

`src/cueplayer/playback/audio_engine.py`:

- Replaced `self._mtc_timer` (a `QTimer`) with `self._mtc_thread_stop` (a
  `threading.Event`) and `self._mtc_thread` (a daemon `threading.Thread`).
- Added `_start_mtc_thread()` / `_stop_mtc_thread()` / `_mtc_thread_loop()`. The loop
  paces itself with `self._mtc_thread_stop.wait(0.004)` — the same 4 ms cadence the old
  `QTimer` used — and calls the existing, unmodified `self._mtc_tick()` on every wake.
  `_start_mtc_thread` is idempotent; `_stop_mtc_thread` sets the stop event and joins the
  thread (bounded 1 s timeout) before returning.
- Replaced every `self._mtc_timer.start()/.stop()` call site with
  `self._start_mtc_thread()` / `self._stop_mtc_thread()`: in `play()` (both the
  real-stream path and the failed-stream-open early-return path), in `pause()`, and in
  `shutdown_midi_outputs()`.
- `_mtc_tick()` itself is **unchanged** — it was already safe to call off the GUI thread
  (see Thread safety below).
- Added a module-level `log = logging.getLogger(__name__)` (this file previously had no
  logger) and an `import logging`, used only to log (never crash on) an unexpected
  exception inside the tick loop.

No change to `MtcOutput`, `MidiCueNotes`, the LTC/audio callback path, video sync, the MA
exporter, persistence, or any UI/rendering code. `Playback Engine` remains the sole
playback clock; this is purely a scheduling-thread change for MTC/MIDI-cue-note pacing.

## Thread / scheduling safety

- `MtcOutput` and `MidiCueNotes` already guard every method with their own
  `threading.Lock` (pre-existing), so `_mtc.tick()` / `.on_play()` / `.on_seek()` /
  `.on_pause()` / `_midi_cues.update()` etc. were already safe to call concurrently from
  a non-GUI thread versus GUI-thread callers (`play()`, `pause()`, `seek()`).
- `AudioEngine._mtc_tick()` reads `self.raw_position` (lock-protected inside
  `AudioEngine`), and a few plain `int`/`tuple` bookkeeping fields
  (`_mtc_seen_loop_sequence`, `_mtc_source_key`, `_loop_discontinuity_sequence`) that are
  also touched by `play()`/`seek()` on the GUI thread. These are not additionally locked,
  but `MtcOutput.tick()`'s own re-anchor logic (already exercised by
  `tests/playback/test_mtc_discontinuity.py`) is idempotent under a redundant or delayed
  reset — at worst a benign extra/late full-frame resend, never a duplicate quarter-frame
  burst, a stale-TC leak, or a crash. This mirrors the exact tolerance the existing
  `tick()` implementation already provides for GUI-thread jitter.
- `_stop_mtc_thread()` joins the thread (bounded) before `shutdown_midi_outputs()` closes
  the MIDI port, so there is no output-device close/reopen race with an in-flight send.
- The thread is `daemon=True` so it can never hang process shutdown; `_stop_mtc_thread` is
  still called from `pause()`/failed-`play()`/`shutdown_midi_outputs()` for a clean,
  bounded stop in the common paths.
- No behavior change to seek/pause/stop semantics: the same `on_play`/`on_seek`/
  `on_pause`/`tick()` calls fire from the same call sites, just paced by a plain thread
  instead of a `QTimer`.

## Regression test

`tests/playback/test_mtc_gui_stall_independence.py` (new):

- `test_mtc_thread_keeps_ticking_with_zero_qt_event_loop_processing` — never calls
  `QCoreApplication.processEvents()` or runs any Qt event loop. Starts the MTC thread,
  sleeps 0.25 s of real wall-clock time doing nothing else, and asserts quarter-frame
  messages were actually sent. If MTC scheduling regressed to depending on a GUI
  `QTimer`, zero messages could ever arrive here (a `QTimer` cannot fire outside a Qt
  event loop), so this test fails loudly on a regression back to the root cause. Also
  asserts `_stop_mtc_thread()` actually stops delivery (no further messages after stop)
  and clears `_mtc_thread`.
- `test_mtc_thread_resume_after_stall_does_not_burst_stale_frames` — a large single
  `tick()` gap (simulating a long stall) re-anchors instead of dumping a multi-second
  backlog of quarter frames (bounded to ≤ 9 messages), guarding against a "burst stale TC
  on resume" regression.

Both tests run under the offscreen Qt platform with no real MIDI/audio device.

## Tests performed

- `tests/playback/test_mtc_gui_stall_independence.py`,
  `tests/playback/test_mtc_discontinuity.py`, `tests/playback/test_ltc_clip_playback.py`
  — 30 passed.
- `tests/playback` (excluding `test_video_sync.py`, a known Windows access-violation
  crash unrelated to this change) — 274 passed, 3 pre-existing failures (see below), 0
  caused by this change.
- `git diff --check` — clean.

## Known baseline failures / hangs (not touched, pre-existing)

- `tests/playback/test_video_sync.py::test_exact_frame_replaces_approximate_on_land` —
  crashes the interpreter with a Windows access violation in a background thread
  (`concurrent.futures.thread._worker`); already documented as a known pre-existing
  Windows video-sync crash in `.ai/NEXT_TASK.md` history. Not run to completion (excluded
  per task instructions), not caused by or related to this change (this task never
  touches `video_sync.py`).
- `tests/playback/test_ndi_probe.py::test_ensure_ndi_runtime_search_path_adds_dll_dir` —
  pre-existing failure, documented in `.ai/NEXT_TASK.md` as a parked, non-blocking known
  issue. NDI is explicitly out of scope for this task.
- `tests/playback/test_song_use_left_ltc.py::test_file_ltc_right_strips_right_from_music`
  and `::test_song_use_left_ltc_routes_left_to_ltc_bus` — pre-existing failures,
  documented in `.ai/NEXT_TASK.md` as parked "routing assertions" issues unrelated to
  MTC/GUI-thread scheduling.
- `tests/ui/test_cue_list_playhead_scroll.py`, `tests/ui/test_timeline_video_track_controls.py`,
  `tests/ui/test_transport_main_window_center.py` — known to hang/crash the interpreter
  under the offscreen Qt test platform (documented in `.ai/NEXT_TASK.md`); not run, per
  task instructions to avoid known hangs.

## Manual verification checklist (for a human on Windows)

1. Load a song with music audio, LTC enabled, and MTC output enabled to a real or virtual
   MIDI port (e.g. loopMIDI / Bome).
2. Press Play. Confirm audio plays and a MIDI monitor shows quarter frames advancing.
3. While playing, single-click the CuePlayer main window's title bar (a click, not a
   drag) — confirm MTC keeps advancing with no stall in the MIDI monitor.
4. While playing, press-and-hold the main window's title bar for a few seconds without
   moving the mouse — confirm MTC keeps advancing continuously during the hold (this is
   the case that used to freeze).
5. While playing, drag the main window's title bar around the screen for several
   seconds — confirm MTC keeps advancing throughout the drag, with no gap and no burst of
   stale timecode when you release.
6. Repeat steps 3–5 with the Clean Video Output window's title bar instead — confirm the
   same result.
7. Confirm audio itself (music + audible LTC tone, if routed to a monitored channel)
   never audibly glitches during any of the above — it shouldn't have before or after this
   change, since it was never on the GUI thread.
8. Confirm pause / stop / seek during and after a title-bar drag still behave normally
   (correct TC at the new position, no duplicate or stale MTC).
9. Confirm app shutdown while MTC is enabled and playing still exits cleanly (no hang).
