# Timing Architecture Diagnostic (Zoom / Mark / Title-Bar Timecode Drop)

Date: 2026-09-07. Branch: `technical-audit-0815-028d`. Baseline: `613338b`.
Status: **diagnostic only — no production code changed.**

Scope: static architecture audit of Playback Clock / Audio / LTC / MTC / Main UI
Timecode Display / Clean Video Output / Timeline Zoom / Mark creation / Qt GUI
thread / background workers, to classify four reported symptoms:

1. Occasional Timecode drop while zooming the Timeline with the mouse wheel.
2. Occasional Timecode drop while creating/dropping a Mark.
3. Clean Video Output freezes while the Windows title bar (main window or Clean
   Video Output window) is held/dragged.
4. Main UI Timecode display freezes during the same title-bar hold/drag.

No production code, playback engine, LTC/MTC scheduling, or video rendering was
modified in this session. Every finding below is cited to a real file/line in
this repo, read directly (no assumptions carried over from memory of other
projects). Where static reading could not settle a question, it is marked
**UNKNOWN — NEEDS INSTRUMENTATION** rather than guessed.

---

## 1. Executive Summary

- **The single source of truth for the playback clock is `AudioEngine._position_frame`**
  (`src/cueplayer/playback/audio_engine.py:107`), advanced exclusively inside the
  PortAudio native callback thread (`_make_stream_callback`, `audio_engine.py:2215-2407`)
  under `self._lock`. Music, the generated/mirrored **LTC waveform**, and Video-clip
  audio are all rendered into the **same output buffer, in the same callback, in the
  same thread** (`audio_engine.py:2331-2378`) — LTC output continuity is therefore
  physically tied to audio callback continuity; it cannot desync from music.
- **MTC** was already fixed in a prior session (`.ai/handoffs/2026-09-07_MtcTitleBarStallFix.md`,
  commit referenced as `fe50976…`): `AudioEngine._mtc_thread` is a dedicated daemon
  thread paced by `threading.Event.wait(0.004)` (`audio_engine.py:1311-1358`), completely
  independent of the Qt GUI event loop. Confirmed by re-reading the current code — the
  fix is present and unchanged.
- **This audit's new finding: the exact same architectural bug the MTC fix solved is
  still present, unfixed, for two other consumers of `AudioEngine.position_changed`** —
  the **Main UI Timecode display** and **Clean Video Output frame scheduling** are both
  driven from `AudioEngine._poll`, a **GUI-thread `QTimer`** (`audio_engine.py:205-207`,
  16 ms interval) → `MainWindow._on_position_changed` (`main_window.py:5334`), which
  Windows suspends for the full duration of a native title-bar move/resize modal loop —
  the identical mechanism documented in the MTC handoff. Unlike MTC, **neither of these
  two consumers has been moved off that timer.**
  - For the **UI Timecode display**, this is provably cosmetic — Issue 4 classifies as
    **D (display-only freeze)**, High confidence — because the chain only *reads*
    `AudioEngine.position` (a cheap, always-correct property) and writes it to display
    widgets; nothing downstream is an actual output.
  - For **Clean Video Output**, the same timer also gates `video_sync.update_position()`
    — the *entry point that decides which frame should be showing*. During a title-bar
    drag, this call is never made, so video scheduling does not merely fail to *present*
    a frame, it never even *requests* one. On top of that, final pixel presentation
    (`VideoPreviewWidget.paintEvent`, `video_preview.py:153-191`) is itself an ordinary
    `QWidget`/`QPainter` paint reached only via `QWidget.update()` — a Qt-event-loop-only
    mechanism that cannot run during the modal loop regardless of which thread requested
    it. Issue 3 therefore has **two independent, stacked causes**, detailed in §13/§16.
- **Zoom (Issue 1) and Mark creation (Issue 2) share one confirmed root cause**: both
  invalidate `TimelineWidget._scrub_backdrop` (`timeline_widget.py:2454-2457` for Mark,
  `2497-2532` for zoom-gesture-end), and the **next paint event synchronously rebuilds
  it** via `_rebuild_scrub_backdrop()` (`timeline_widget.py:3242-3329`) on the **GUI
  thread**. The code's own inline comment and instrumentation document a **measured
  64–186 ms synchronous hitch** for this rebuild (`timeline_widget.py:3258-3263`), with
  a live `ui.event_loop_long_task_ms` perf counter that fires whenever it exceeds one
  frame budget (`timeline_widget.py:3327-3329`). This is a GUI-thread stall (classification
  **D + E**, High confidence) that can plausibly add jitter to GIL-needing background
  work (**F**, Medium confidence — CPython's GIL switch interval bounds how bad this can
  get; it is not a full lockout). No code path found in either Zoom or Mark creation
  touches `AudioEngine._lock`, `_position_frame`, `MtcOutput`, or `MidiCueNotes` directly,
  so **A/B/C (actual clock/LTC/MTC output discontinuity) are not supported by the static
  evidence** for either issue; full certainty on MTC/audio jitter needs the instrumentation
  in §20 (which mostly already exists in this codebase — see below).
- **CuePlayer already has a rich, low-overhead performance-instrumentation framework**
  (`src/cueplayer/diagnostics/perf.py`, enabled via `CUEPLAYER_PERF=1`) that already
  measures almost everything this diagnostic needs: `timeline.mark_backdrop.rebuild_ms`,
  `ui.event_loop_long_task_ms`, `video.present_delayed_by_timeline_ms`,
  `audio.callback.interval_max_s` / `deadline_miss_count` (real audio continuity), and a
  built-in "Tools → Profile UI 5s" stdlib `cProfile` capture
  (`main_window.py:5724-5765`). §20's instrumentation plan is therefore mostly "turn on
  what's already there and read it," plus one small proposed addition (MTC-tick-interval
  span) to close the one real gap found.

---

## 2. Timing Architecture Map

| Subsystem | Source of truth clock | Thread | Scheduling mechanism | Depends on Qt GUI event loop? | Blockable by Windows title-bar modal loop? | Needs Python GIL? | Can block another subsystem? | Output vs presentation |
|---|---|---|---|---|---|---|---|---|
| **Playback Engine position** | `AudioEngine._position_frame` (`audio_engine.py:107`) | PortAudio native callback thread | Advanced every audio block inside `_make_stream_callback` (`audio_engine.py:2215-2407`) | No | No | Briefly, per callback, for the Python glue around the callback (numpy releases GIL for its C loops) | Holds `AudioEngine._lock` briefly per callback | **Actual clock** — ground truth |
| **Music audio** | same callback | PortAudio callback thread | `_music_chunk` (`audio_engine.py:2055`) mixed into `outdata` | No | No | Same as above | No | **Actual output** |
| **LTC** | same callback, `_ltc_chunk` (`audio_engine.py:2140-2178`) | PortAudio callback thread | Pre-cached PCM array slice (`self._ltc_pcm[start:end]`) or clip-table slice — O(chunk), no per-sample Python loop | No | No | Brief, cheap | No | **Actual output** — literally the same buffer as music |
| **MTC + MIDI cue notes** | `AudioEngine._mtc_thread` (`audio_engine.py:1311-1358`) reading `raw_position` | Dedicated daemon thread (`threading.Thread`, `name="mtc-tick"`) | `Event.wait(0.004)` wall-clock pacing, calls `_mtc_tick()` → `MtcOutput.tick()` / `MidiCueNotes.update()` | **No (fixed)** | **No (fixed)** | Yes, every 4 ms, but each tick is fast pure-Python + a lock (`mtc_output.py:268-334`, `midi_cue_notes.py:101-114`) | Holds `MtcOutput._lock` / `MidiCueNotes._lock` (each's own lock, not shared with `AudioEngine._lock`) | **Actual output** |
| **Main UI Timecode display** (transport bar TC, Cue Monitor "Output Timecode" clock, Timeline playhead position) | reads `AudioEngine.position` | **GUI thread** | `AudioEngine._poll` `QTimer` (16 ms, `audio_engine.py:205-207`) → `position_changed.emit()` → `MainWindow._on_position_changed` (`main_window.py:5334`) → `transport.set_times` / `monitor.set_position` / `_refresh_output_timecode_clock` / `timeline.set_position` | **Yes** | **Yes (unfixed)** | Yes (display formatting is pure Python) | No — read-only | **Presentation only** |
| **Clean Video Output — scheduling** ("which frame should show now") | reads `AudioEngine.position` via the *same* `_poll` → `_on_position_changed` chain | **GUI thread** | `MainWindow._on_position_changed` → `video_sync.update_position(seconds, source="engine")` (`main_window.py:5363`) | **Yes** | **Yes (unfixed)** | Dispatch logic is Python but cheap; actual decode is off-thread (see next row) | No | Decides *which* frame — not itself pixels |
| **Clean Video Output — decode** | n/a (per-request) | `VideoSyncController._async_pool` (`ThreadPoolExecutor`, `video_sync.py:298`) worker thread(s) | `_async_pool.submit(self._async_worker_loop)` (`video_sync.py:2929,3258,3262`), result delivered via `_async_frame_ready` Signal (`video_sync.py:225`) | No (decode itself) | No (decode itself) | Yes, per frame conversion | No | Produces frame data, not yet on screen |
| **Clean Video Output — presentation** | n/a | **GUI thread** | `VideoSyncController.frame_changed` → `MainWindow._on_video_frame` (`main_window.py:2328`) → `CleanVideoOutputWindow.set_qimage` → `VideoPreviewWidget.set_qimage` → `self.update()` (`video_preview.py:84-95`) → Qt-scheduled `paintEvent` (`video_preview.py:153-191`, plain `QPainter`/`QImage.drawImage`, no OpenGL) | **Yes — unavoidably, by Qt's widget-paint model itself, not by a scheduling choice** | **Yes** | Paint calls need GIL but are individually fast | No | **Pixels only** |
| **Timeline playhead / waveform / Mark redraw** | reads `AudioEngine.position` via same chain | GUI thread | `TimelineWidget.set_position` (called from `_on_position_changed`) → `update()` → `paintEvent` | Yes | Yes | Yes | Can itself stall the GUI thread for up to ~186 ms on a backdrop rebuild (§13) | **Presentation only** |
| **NDI output** | reads frames from the same `_on_video_frame` fan-out | GUI thread hands off to `ndi_output.py`'s own worker thread (`threading.Thread`, `ndi_output.py:455`) with `threading.Event` wake/stop (`ndi_output.py:328-329`) | Frame handed off via `self._ndi_output.send_frame(frame)` (`main_window.py:2389`) from the GUI-thread `_on_video_frame` | Partially — the *hand-off* is GUI-thread-gated (same freeze as Clean Video during title-bar drag); the worker thread itself is independent once it has a frame | Yes, for new frames during the drag | Yes for the hand-off | No | Informational only — out of scope per task instructions, noted because it shares the frozen hand-off path |

---

## 3. Thread Ownership Map

- **PortAudio native callback thread** (owned by `sounddevice`/PortAudio, not
  Python-spawned) — `AudioEngine._make_stream_callback` (`audio_engine.py:2215`). Runs
  music + LTC + video-clip-audio mixing + real position advance. Independent of Qt
  entirely.
- **`mtc-tick` daemon thread** (`threading.Thread`, `audio_engine.py:1316-1322`) — MTC
  quarter-frames + MIDI cue notes, paced by `Event.wait(0.004)`. Fixed in the prior
  session; unaffected by Qt.
- **GUI thread** (Qt main thread) — owns every `QTimer`, every `QWidget` (including
  `CleanVideoOutputWindow` / `VideoPreviewWidget`), `AudioEngine._poll`/`_silent_timer`,
  all of `TimelineWidget`'s timers, all of `VideoSyncController`'s timers
  (`_flush_timer`, `_scrub_preload_timer`, `_play_budget_timer`, `_scrub_preview_timer`,
  `_scrub_pause_timer`, `_land_retry_timer`, `_resume_watchdog`, `_seek_liveness_timer`
  — `video_sync.py:263-396`), and the position/UI/video fan-out
  (`MainWindow._on_position_changed`).
- **`VideoSyncController._async_pool`** (`ThreadPoolExecutor`, `video_sync.py:298`) —
  video frame decode for Clean/Preview output.
- **Video waveform / scrub-preview executors** (separate from the above, Timeline
  waveform display only, not the live playback video path):
  `video_waveform_artifact.py:1078` (`_executor`), `video_clip_waveform.py:201`
  (`vid-wave`, 2 workers), `scrub_frame_cache.py:137` (`scrub-vid`).
- **Video-clip audio mixer executor** — `video_audio_mixer.py:89` (`vid-audio`, 1
  worker) — decodes embedded video-clip audio off-RT; the PortAudio callback only reads
  already-decoded windows.
- **`ndi-*` worker thread** — `ndi_output.py:455`, its own `Event`-paced send loop,
  independent once fed a frame.
- **Misc single-purpose executors** — `ltc-cache`, `audio-resample`, `ltc-detect`
  (`audio_engine.py:169,197-198`), `ui-audio-load`, `ui-audio-prefetch`,
  `ui-video-probe` (`main_window.py:1071-1113`) — all one-shot / prewarm work, not
  steady-state timing paths; not relevant to the four issues.
- **`web_remote`** (`webrtc_listen.py`, `server.py`) — its own threads; unrelated to
  the four issues (out of scope, not audited further).

---

## 4. Timer Inventory

Legend: **[OUTPUT]** = if delayed, a real external Timecode/audio signal is late/wrong.
**[DISPLAY]** = if delayed, only what's on screen is stale; nothing external is affected.

| Name | File:line | Owner | Thread | Interval | Purpose | Clock dependency | GUI-loop dependency | Blocking risk |
|---|---|---|---|---|---|---|---|---|
| `_poll` | `audio_engine.py:205-207` | `AudioEngine` | GUI | 16 ms | Emits `position_changed`; drives **UI display AND video scheduling entry point** | Reads real position | **Yes — stops during title-bar modal loop** | **[DISPLAY]** for UI TC; **[OUTPUT-ADJACENT]** for video (gates the scheduling *decision*, not an output signal itself, but the practical effect for Issue 3 is real) |
| `_silent_timer` | `audio_engine.py:208-210` | `AudioEngine` | GUI | 16 ms | Bookkeeping-only fake clock, used only when no real output stream exists at all (no music/LTC/video-audio) | Advances a synthetic position | Yes | **[OUTPUT]** only in the rare "nothing audible loaded" case — not the reported issues' scenario (all four reports involve active playback with real audio) |
| `_mtc_thread` | `audio_engine.py:1311-1358` | `AudioEngine` | Dedicated daemon thread | 4 ms (`Event.wait`) | MTC quarter-frames + MIDI cue notes | Reads real position | **No (fixed)** | **[OUTPUT]** — already hardened |
| `_zoom_preview_repaint_timer` | `timeline_widget.py:397-398` | `TimelineWidget` | GUI | ≤33 ms (30 Hz cap) | Throttles zoom-preview repaints during a continuous wheel gesture | n/a | Yes | **[DISPLAY]** — cheap, coalesced |
| `_zoom_quality_timer` | `timeline_widget.py:407-410` | `TimelineWidget` | GUI | 280 ms (single-shot debounce) | Fires the one expensive full backdrop rebuild after a zoom gesture goes idle | n/a | Yes | **[DISPLAY]** but the rebuild itself is the ~64-186 ms GUI stall (§13) |
| `_scrub_timer` | `timeline_widget.py:421` | `TimelineWidget` | GUI | (scrub-drag pacing) | Not touched by this audit (scrub path, out of scope) | n/a | Yes | Not evaluated |
| `_transport_view_freeze_timer` | `timeline_widget.py:284` | `TimelineWidget` | GUI | n/a | Not touched by this audit (out of scope) | n/a | Yes | Not evaluated |
| `_cue_list_refresh_timer` | `main_window.py:1098` | `MainWindow` | GUI | debounced (`_schedule_cue_list_refresh`, `main_window.py:5943-5944`) | Coalesces Cue Monitor `refresh_list()` after Mark edits | n/a | Yes | **[DISPLAY]** — decoupled from the mark-drop action itself (see §12) |
| `_autosave_timer` | `main_window.py:2711-2725` | `MainWindow` | GUI | user-configured minutes | Periodic project save | n/a | Yes | **[DISPLAY-adjacent]** — confirmed NOT triggered synchronously by Mark creation (§12) |
| `_settings_debounce` | `video_output_window.py:90-93` | `CleanVideoOutputWindow` | GUI | 300 ms single-shot | Debounces `settings_changed` after resize/menu changes | n/a | Yes | Cosmetic only |
| `_flush_timer`, `_scrub_preload_timer`, `_play_budget_timer`, `_scrub_preview_timer`, `_scrub_pause_timer`, `_land_retry_timer`, `_resume_watchdog`, `_seek_liveness_timer` | `video_sync.py:263-396` | `VideoSyncController` | GUI | various | Video pipeline state-machine pacing (scrub, land, resume, watchdog) | n/a | Yes | Not touched by this audit's four issues (they concern engine-driven playback, not scrub); noted for completeness only |
| `_secondary_clear_timer` | `cue_monitor_panel.py:396` | Cue Monitor | GUI | n/a | Out of scope | n/a | Yes | Not evaluated |
| `_ltc_idle_timer`, `_audio_load_timer` | `main_window.py:1094,1138` | `MainWindow` | GUI | n/a | Out of scope (LTC detect idle / audio load) | n/a | Yes | Not evaluated |

**Which QTimers are "only updates display" vs "actually controls output":**
- **Actually controls output**: none of the GUI-thread `QTimer`s do — real output
  (audio/LTC via PortAudio callback, MTC via its own daemon thread) is **not** timed by
  any `QTimer`.
- **Only updates display**: `_poll`'s UI-display fan-out (transport/monitor/timeline
  labels), all `TimelineWidget` repaint timers, `_cue_list_refresh_timer`,
  `_settings_debounce`.
- **Gates a real decision without itself being "output"**: `_poll`'s video-scheduling
  fan-out — `video_sync.update_position()` is not an output device write, but not
  calling it means Clean Video Output never even attempts to catch up, which is the
  practical mechanism behind Issue 3.

---

## 5. Playback Clock Path

`AudioEngine._position_frame` (`audio_engine.py:107`), advanced under `self._lock`
inside the PortAudio callback (`audio_engine.py:2300-2354`). `AudioEngine.raw_position`
(`audio_engine.py:604-625`) reads it and **interpolates** between callbacks using
`time.monotonic()` so the UI doesn't stick to the audio-block grid. `AudioEngine.position`
(`audio_engine.py:627-633`) applies the sync-offset calibration on top. This property is
cheap (one lock acquire/release, no I/O, no allocation) and is the value every consumer
in this report ultimately reads — it is always correct/live; nothing in Zoom, Mark
creation, or the title-bar freeze ever corrupts it. Confirmed no code path in
`timeline_widget.py`'s zoom/mark code or `main_window.py`'s mark-add path touches
`self._lock`, `_position_frame`, `_pos_epoch_frame`, or `_pos_epoch_mono` directly.

---

## 6. Audio Path

`_make_stream_callback` (`audio_engine.py:2215-2407`) is a closure installed as
`sd.OutputStream`'s `callback=` (`audio_engine.py:2547,2562`). Everything — position
advance, loop wrap, music chunk, LTC chunk, video-clip-audio chunk, click mix, routing —
happens inside this one native callback, under `self._lock`, entirely independent of Qt.
The file already carries its own continuity instrumentation
(`_cb_count`/`_cb_underflow`/`_cb_interval_max`/`_cb_deadline_miss`, surfaced via
`audio_callback_continuity()` and `audio.callback.*` perf attrs, `audio_engine.py:2430-2477`)
— this is the direct, already-built way to prove or disprove whether a Zoom/Mark GUI
stall ever actually disturbs the audio callback (see §20).

**Callback's own GIL footprint** (cross-verified by a second, independent audit pass over
the same file): the stream opens with `blocksize=0` (`audio_engine.py:2548`), i.e.
driver-controlled buffer sizing (PortAudio/WASAPI decide the callback cadence, not this
code) — so the exact callback-to-callback interval cannot be pinned down from static
reading alone. Inside the callback, the only Python-level (non-vectorized) loop is
`apply_routing`'s `for src_ch, destinations in route.items(): for dest_ch in
destinations:` (`src/cueplayer/routing/matrix.py:35-38`), bounded by a fixed, small
number of source buses/destination channels — it does not grow with frame count, Mark
count, or Clip count. `_mix_clicks` (`audio_engine.py:1408-1430`) is an `O(1)` no-op in
normal playback (`self._calib_click_frames` is empty outside calibration,
`audio_engine.py:1410`). This supports (but does not itself prove — see §20) the
conclusion that the callback's own per-invocation GIL hold time is small and does not
scale with anything Zoom/Mark-creation touches; the open question remains whether an
*external* GUI-thread GIL hold (the backdrop rebuild, §11/§12) can delay this thread's
turn to run its own small amount of work long enough to matter.

---

## 7. LTC Path

LTC is **not a separate generator/output stage** — it is one more array slice
(`_ltc_chunk`, `audio_engine.py:2140-2178`) mixed into the exact same `outdata` buffer as
music, in the exact same PortAudio callback. The three LTC modes (`_uses_clip_ltc`,
file-source passthrough, `_uses_generated_ltc`) all resolve to O(chunk) numpy slicing —
no per-sample Python loop, no lock other than the already-held `self._lock`, no GIL-heavy
work. LTC output continuity is therefore mathematically identical to audio callback
continuity: whatever the `audio.callback.*` counters say about underflow/deadline misses
is a direct proxy for LTC health too.

---

## 8. MTC Path

Already covered by the prior session's fix, re-verified in this audit
(`audio_engine.py:1311-1358`, `mtc_output.py`, `midi_cue_notes.py`). `MtcOutput` and
`MidiCueNotes` each guard their own state with their own `threading.Lock` — neither
shares a lock with `AudioEngine`. `_mtc_tick()` (`audio_engine.py:1343-1358`) reads
`self.raw_position` (cheap, lock-protected) and a few plain bookkeeping ints; the note
in `audio_engine.py:211-223` documents why this is safe off the GUI thread. One
secondary observation (not a bug, just an efficiency note): `MidiCueNotes.update()`
(`midi_cue_notes.py:101-114`) does `for mark in song.marks:` every 4 ms tick
(`_marks_to_fire_locked`, `midi_cue_notes.py:122-139`) — an O(total marks in the song)
scan, unconditional even when MIDI cue notes are disabled for most lanes. For realistic
show sizes (tens to low hundreds of marks) this is sub-millisecond and not implicated in
any of the four issues; flagged only for completeness, not recommended for action in
this diagnostic-only phase.

**Real, benign, but unaddressed race condition** (independently confirmed by two separate
audit passes this session — the MTC/audio-path audit and the Mark-creation-trace audit —
converging on the same finding): `MidiCueNotes._lock` (`midi_cue_notes.py:36`) only
guards `MidiCueNotes`'s own fields (`_song`/`_playing`/`_last_position`); it is never held
by `Song.add_mark` (`domain/models.py:617-626`), which runs on the GUI thread and does a
plain `self.marks.append(mark)` followed by two unlocked `sort_marks()` calls
(`domain/models.py:620,625`, each a `list.sort()`). So the `mtc-tick` thread's `for mark
in song.marks:` scan (`midi_cue_notes.py:129`) can run concurrently with a GUI-thread
Mark add/sort with **no lock coordinating the two**. Under CPython's GIL this cannot
corrupt memory or raise (list `sort()`/`append()` are atomic with respect to a
concurrent read-only iteration in the sense that a reader will see either the pre- or
post-mutation list state, never a torn one), so the realistic worst case is a single MTC
tick reading a stale ordering or missing the just-added Mark for one 4 ms cycle — not a
Timecode-output interruption. This is real architecture debt worth naming and fixing with
a proper lock in a future session, but it does **not** explain any of this diagnostic's
four reported symptoms and is not recommended for action in this diagnostic-only phase.

---

## 9. UI TC Display Path

Three call sites use the label "Timecode display" loosely; all three are fed by the
same chain and are all presentation-only:

1. **Transport bar TC** — `self.transport.set_times(seconds, self.engine.duration)`
   (`main_window.py:5352`).
2. **Cue Monitor "Output Timecode" clock** — `self._refresh_output_timecode_clock(seconds)`
   (`main_window.py:5356`) → `self.engine.output_timecode_state(position)`
   (`audio_engine.py:247-302`, a pure computation from `self.position` — no lock beyond
   what the `.position` property itself takes) → `self.monitor.set_output_timecode(...)`
   (`main_window.py:6383-6387`) — pure text formatting.
3. **Timeline playhead / ruler position** — `self.timeline.set_position(seconds)`
   (`main_window.py:5350`).

All three are called from `MainWindow._on_position_changed` (`main_window.py:5334-5399`),
itself only invoked by `AudioEngine.position_changed.emit(...)`, itself only emitted from
`AudioEngine._emit_position` (`audio_engine.py:1360`), itself only called from the
GUI-thread `_poll` `QTimer` (`audio_engine.py:207`) or from direct calls after
`seek`/`pause` (also GUI thread, also not real-time-critical). **No code path here writes
to `AudioEngine._position_frame`, `MtcOutput`, or `MidiCueNotes` — it is exclusively a
reader.** This is why Issue 4 classifies as D with High confidence: the mechanism that
freezes it (Windows suspending GUI-thread `QTimer`s during the modal loop) is proven by
the same code-level argument the MTC handoff already made for the old MTC bug, and
nothing downstream of this specific chain is an actual output.

---

## 10. Clean Video Output Path

Full chain, GUI-thread portions in **bold**:

1. **`AudioEngine._poll` (16 ms `QTimer`) fires** → `_emit_position()` →
   `position_changed.emit(pos)`.
2. **`MainWindow._on_position_changed(engine_seconds)`** (`main_window.py:5334`) computes
   song time, then (when not gated by scrub/land state)
   **`self.video_sync.update_position(seconds, source="engine")`** (`main_window.py:5363`).
3. `VideoSyncController.update_position` (`video_sync.py:2247-2336`, GUI thread but
   cheap/dispatch-only) resolves the active clip, decides scrub vs. normal playback
   policy, and for normal playback submits decode work to
   `self._async_pool` (`ThreadPoolExecutor`, `video_sync.py:298`) — **decode itself runs
   on a worker thread**, off the GUI thread.
4. The worker thread finishes and signals back via `_async_frame_ready`
   (`video_sync.py:225`, a Qt `Signal` — cross-thread emission auto-marshals onto the
   receiver's thread, i.e. the GUI thread, through the Qt event loop), eventually calling
   **`self.frame_changed.emit(frame)`** (`video_sync.py:4086`).
5. **`MainWindow._on_video_frame(frame)`** (`main_window.py:2328-2394`, GUI thread) —
   converts RGB→`QImage` (`rgb_frame_to_qimage`) and calls
   **`self.clean_output_window.set_qimage(image)`** / **`self.video_preview.set_qimage(image)`**.
6. **`VideoPreviewWidget.set_qimage`** (`video_preview.py:84-95`) stores the image and
   calls **`self.update()`** — a `QWidget.update()`, which only *schedules* a repaint by
   posting an event to the Qt event queue; it does not paint synchronously.
7. **`VideoPreviewWidget.paintEvent`** (`video_preview.py:153-191`) — plain `QPainter`,
   `painter.drawImage(...)`, no OpenGL — runs only when the Qt event loop next processes
   the posted paint event.

**Two independent, stacked reasons Clean Video Output freezes during a title-bar drag:**

- **Reason A — scheduling never runs.** Step 1-2 is gated by the exact same GUI-thread
  `QTimer` mechanism the old MTC bug depended on. During the modal loop, `_poll` does
  not fire, so `_on_position_changed` — and therefore `video_sync.update_position()` —
  is **never called** for the whole duration of the drag. No new frame is even
  requested, regardless of how fast the decode worker thread could otherwise produce
  one.
- **Reason B — even a ready frame cannot reach the screen.** Steps 4-7 depend on the Qt
  event loop to (a) deliver the cross-thread `_async_frame_ready` signal to the GUI
  thread and (b) process the posted repaint from `QWidget.update()`. Both (a) and (b)
  are Qt-event-loop mechanisms with **no independent-thread bypass available to a plain
  `QWidget`/`QPainter` surface** — this is a hard Qt widget-thread-affinity property, not
  a scheduling choice made in this codebase. So even if Reason A were fixed (scheduling
  moved to a background-paced trigger, mirroring the MTC fix), a frame that finished
  decoding during the drag would still queue behind the same frozen event loop before
  its pixels could appear — it would just be a queued repaint waiting for the drag to
  end, rather than a queued request waiting to be dispatched. **This is architecturally
  different from the MTC fix**: MTC's "presentation" is a raw MIDI byte send with no Qt
  paint step, so decoupling its pacing from `QTimer` fully solved it. Clean Video
  Output's presentation is fundamentally a Qt widget paint, which needs the Qt event
  loop by construction.

What is **not** the cause: there is no GUI-thread `QTimer` literally driving decode or
frame *scheduling* logic on a private cadence the way the old `_mtc_timer` did — decode
dispatch is triggered by the position fan-out (Reason A), and decode execution itself is
already correctly off-thread (`_async_pool`). This is a different failure shape from the
original MTC bug, not a copy of it, even though the *entry point* (`_poll`) is literally
the same timer.

**On the "catch up vs. jump" question**: because `update_position(seconds, ...)` always
computes "what should be showing at *this* `seconds` value" fresh, rather than replaying
history, and step 4's signal delivery does not artificially queue every intermediate
frame for guaranteed delivery (Qt does not coalesce arbitrary signal emissions by
default, but `_on_video_frame` always presents whatever the *latest* processed frame is,
and `video_sync.py`'s own scrub/generation-guard counters — e.g.
`video.playback.frame_drop.reason.newer_already_presented`,
`video.async_stale_drop` — exist specifically to drop stale in-flight frames), the
practical expectation is a single jump to the post-drag position rather than a
frame-by-frame catch-up burst. **This is inferred from the state-machine's stale-drop
counters, not directly observed** — confirming it needs the manual reproduction + perf
dump in §20.

**NDI**: `main_window.py:2388-2389` sends frames from the same GUI-thread
`_on_video_frame` handler that Clean Video Output uses, so new NDI frames are gated by
the identical Reason A during a drag. `ndi_output.py`'s own worker thread
(`ndi_output.py:455`) is independent once fed a frame, so NDI itself does not add a third
mechanism — informational only, per task scope (NDI is out of scope for any fix).

---

## 11. Zoom Execution Trace

`wheelEvent` (`timeline_widget.py:5779-5835`) classifies the input device
(mouse-wheel vs. trackpad) and, for a real mouse wheel with no modifier, calls
`_zoom(dy)` → `self.zoom_by(1.12 or 1/1.12)` (`timeline_widget.py:5788-5793`) →
`set_zoom(...)` (`timeline_widget.py:2383-2420`).

**Per-tick cost (every wheel notch) is small and bounded:**
- Recomputes `_pixels_per_second` and `_scroll_x` (arithmetic only,
  `timeline_widget.py:2390-2407`).
- `_begin_view_transform_gesture()` (`timeline_widget.py:2459-2477`) seeds the backdrop
  **only if it is currently null** (cheap check, not a rebuild on every tick), sets a
  `_view_transform_busy` flag, and (re)starts the 280 ms debounce timer
  (`_zoom_quality_timer`).
- `_request_zoom_preview_repaint()` (`timeline_widget.py:2479-2491`) throttles the actual
  repaint to ≤30 Hz.
- During the busy/preview state, `paintEvent` uses `_blit_zoom_preview`
  (`timeline_widget.py:3089`, not read in full this session but referenced structurally
  by `paintEvent`'s `_view_transform_busy` branch, `timeline_widget.py:5891-5920`) — a
  scaled blit of the **already-cached** pixmap, not a re-rasterization.
- **No loop over all Marks/Video Clips/LTC Clips runs per wheel tick** — the only
  per-visible-item work (`_bake_mark_annotation_sprites`, `timeline_widget.py:3337-3421`)
  is scoped to the visible time range (`self._song.mark_slice_in_time_range(t_lo, t_hi)`,
  `timeline_widget.py:3351`) and only runs inside the end-of-gesture rebuild, not per
  tick.

**One expensive synchronous operation, once per gesture (at idle, not per tick):**
`_finish_view_transform_gesture()` (`timeline_widget.py:2508-2532`, fired by the 280 ms
`_zoom_quality_timer` after the wheel goes quiet) calls
**`self._rebuild_scrub_backdrop(reason="zoom_idle")`** synchronously on the GUI thread.
This function (`timeline_widget.py:3242-3329`):
- Allocates two `QPixmap`s sized `(viewport_width + 2×overscan) × height` at the
  widget's device pixel ratio (`timeline_widget.py:3269,3279-3281`).
- Paints the full static layer stack into them: `_paint_static_layers` (spatial: header,
  grid, waveform), then ruler labels, LTC clips, and `_paint_marks` (full Mark bake) into
  a second layered pixmap (`timeline_widget.py:3286-3312`).
- **The waveform-envelope draw itself contains a pure-Python per-pixel-column loop**:
  `_paint_waveform_peaks` (`timeline_widget.py:7017-7089`) does vectorized numpy work to
  compute per-column min/max bucket ranges, but the `for i in np.flatnonzero(valid):`
  loop (`timeline_widget.py:7058`) iterates once per horizontal pixel column
  (~viewport width + 2×128 overscan, so roughly 1500-2500 iterations on a typical
  window), building a `QLineF` per column in interpreted Python before a single batched
  `painter.drawLines(lines)` call. This is CPU-bound, GIL-holding Python work whose cost
  scales with **viewport pixel width, not song length or zoom level directly** (though
  zoom level changes which samples map to each column, not the column count).
- The code's own comment (`timeline_widget.py:3258-3263`) states this was **measured at
  64–186 ms** when the overscan was larger (3.5 screens); it has since been trimmed to a
  smaller 128 px overscan specifically for the `zoom_idle`/playing case
  (`timeline_widget.py:3264-3268`) to reduce this — but the fundamentally synchronous,
  GUI-thread, per-pixel-column-loop nature of the rebuild is unchanged, only its constant
  factor. There is a live perf counter for exactly this scenario:
  `if elapsed >= 16.7: perf_diag.record_ms("ui.event_loop_long_task_ms", elapsed)`
  (`timeline_widget.py:3327-3329`) — i.e., the codebase already flags this rebuild as a
  potential long-task/frame-budget violation whenever it happens.
- No `processEvents()` call was found anywhere in this path (none of the zoom functions
  read call it) — ruling out that specific reentrancy risk.
- No `time.sleep()` or blocking I/O found in this path.
- No lock shared with `AudioEngine` is acquired anywhere in this path (`_rebuild_scrub_backdrop`,
  `_paint_static_layers`, `_paint_waveform_peaks`, `_bake_mark_annotation_sprites` — none
  reference `self._lock`/`AudioEngine`).

**Also relevant** (found while confirming this): `MainWindow._on_video_frame`
(`main_window.py:2328-2394`) already checks `timeline.is_view_transform_busy()`
(`main_window.py:2342-2346`) and, when a video frame becomes ready while zoom is busy,
records `perf_diag.record_ms("video.present_delayed_by_timeline_ms", delay_ms)`
(`main_window.py:2392-2394`) — direct, pre-existing, code-level confirmation that the
developers already anticipated and instrumented "zoom work can delay video frame
presentation."

### Issue 1 classification

| Class | Verdict | Confidence | Basis |
|---|---|---|---|
| A — playback clock discontinuity | Not supported | High (against) | No code in the zoom path touches `AudioEngine._lock`/`_position_frame`. |
| B — LTC output discontinuity | Not supported | High (against) | LTC renders inside the PortAudio callback only; zoom code never touches it. |
| C — MTC output discontinuity | Possible only via GIL jitter, not a direct code path | Medium (against direct causation; Low-Medium for indirect jitter) | `_mtc_thread` is architecturally independent, but a 64-186 ms mostly-Python GUI-thread rebuild **could** add scheduling jitter to the MTC thread's next `_mtc_tick()` wake-up via GIL contention. CPython's GIL switch interval (default ~5 ms) bounds how long any one thread can be starved, so a full multi-tick stall is unlikely, but some added latency on the order of single-digit ms is plausible and **not ruled out by static reading alone**. |
| D — UI/presentation freeze only | **Primary finding** | **High** | Directly caused by `_rebuild_scrub_backdrop` running synchronously on the GUI thread once per zoom gesture; matches the "occasional" (not constant) character of the reported symptom, since it fires once at gesture-end, not every tick. |
| E — GUI event-loop starvation | **Primary finding** | **High** | Same evidence as D — this is, by the code's own measurement, a 64-186 ms synchronous block of the GUI thread, i.e. event-loop starvation by definition. |
| F — Python GIL contention | Plausible contributing factor | Medium | The rebuild's per-pixel-column loop is real, sustained, mostly-interpreted Python work; it would compete for the GIL with the MTC thread's ticks and the audio callback's Python-side glue for the duration of the rebuild. Not verified with real timing data — see §20. |

---

## 12. Mark Creation Execution Trace

Primary path exercised: keyboard-shortcut Mark drop, `MainWindow._add_mark`
(`main_window.py:8929-8952`) — this is the common Show Control workflow (drop a cue
mark at the playhead via a hotkey during rehearsal/playback) and matches the user's
description of "偶爾感覺 Timecode 會掉一下" while dropping a Mark.

1. `mark_at` is read from either `self.playback.position` (while playing) or
   `self.timeline.playhead_seconds()` (`main_window.py:8941-8944`) — cheap reads, no
   lock contention beyond the trivial `AudioEngine.position` property lock.
2. **`self.current_song.add_mark(lane_index, mark_at)`** (`domain/models.py:617-626`):
   appends to `self.marks`, calls **`self.sort_marks()` twice**
   (`domain/models.py:620,625` — once before, once after Cue ID assignment) — each is a
   plain `list.sort()` (Timsort) over the whole song's Mark list
   (`domain/models.py:640-643`). For realistic show sizes (tens to low hundreds of
   marks) this is sub-millisecond and **not** the expensive step. `assign_main_cue_id_for_mark`
   (imported from `domain/main_cue_id.py`, not read in full this session — out of scope,
   pure Cue-ID-numbering logic, no Qt/paint/lock interaction) is likewise a bounded,
   in-memory operation over the mark list.
3. **`self._push_song_undo(AddMarksCommand(...))`** (`main_window.py:8946`) —
   `AddMarksCommand` (`domain/undo.py:61-75`) is a plain dataclass holding one
   `MarkSnapshot`; pushing it onto the undo stack is O(1) (no serialization, no disk I/O).
4. **`self._mark_dirty()`** (`main_window.py:2853-2856`) — sets an in-memory dirty flag
   via `self._project_service.mark_dirty()` and refreshes the window title string. **Does
   not** write to disk. Confirmed autosave (`main_window.py:2711-2725`) is driven by its
   own independent, user-configured-interval `QTimer` (`_autosave_timer`), never
   triggered synchronously from a mark add — so a single Mark drop **never** causes a
   synchronous JSON serialize / disk write.
5. **`self._refresh_marks_ui()`** (`main_window.py:5950-5956`):
   - `self.timeline.bump_mark_backdrop_revision(reason="marks_ui_refresh")`
     (`timeline_widget.py:2454-2457`) → `self._invalidate_scrub_backdrop(...)`
     (`timeline_widget.py:2938-2950`) — **nulls `self._scrub_backdrop`/`self._spatial_backdrop`**,
     i.e. exactly the same cache invalidation Zoom performs at gesture-end.
   - `self.timeline.update()` — schedules (does not synchronously force) a repaint.
   - `self._schedule_cue_list_refresh()` (`main_window.py:5943-5944`) — **debounced**
     via `self._cue_list_refresh_timer.start()`, not called synchronously. The actual
     `self.monitor.refresh_list()` (Cue Monitor full row rebuild — cost proportional to
     total cues/marks in the song, not measured in this session) only runs once that
     timer later fires, decoupled from the mark-drop action itself.
6. **The next `TimelineWidget.paintEvent`** (triggered by the `update()` in step 5, and/or
   by the very next playhead-position paint if playing) finds
   `self._scrub_backdrop is None`, takes the `_can_use_static_backdrop()` → `_blit_scrub_backdrop`
   → `_blit_native_backdrop` path (`timeline_widget.py:3016-3036`), and **self-heals by
   calling `self._rebuild_scrub_backdrop(reason="scrub_seed")` synchronously**
   (`timeline_widget.py:3018-3019`) — **the identical expensive rebuild function Zoom
   uses**, with the identical ~64-186 ms measured cost profile documented in §11. This is
   the direct mechanism by which Mark creation can produce the same visible "Timecode
   drop" symptom as Zoom.

No code in this path (steps 1-6) touches `AudioEngine._lock`, `_position_frame`,
`MtcOutput`, or `MidiCueNotes`. No synchronous full-project JSON serialization. No
exporter code reachable (confirmed: `_add_mark` and everything it calls stays within
`domain/`, `ui/`, and `timeline_widget.py` — nothing under `src/cueplayer/exporters/`
is imported or called on this path, consistent with `AGENTS.md`'s architecture rule).

### Issue 2 classification

| Class | Verdict | Confidence | Basis |
|---|---|---|---|
| A — playback clock discontinuity | Not supported | High (against) | No lock/position-frame contact anywhere in the traced path. |
| B — LTC output discontinuity | Not supported | High (against) | Same reasoning as Issue 1. |
| C — MTC output discontinuity | Possible only via GIL jitter | Low-Medium (against direct causation) | Same GIL-contention reasoning as Issue 1, but the rebuild here is triggered once per mark-drop rather than once per zoom gesture — likely rarer in practice, matching "偶爾" (occasional). |
| D — UI/presentation freeze only | **Primary finding** | **High** | Mark creation invalidates the identical backdrop cache Zoom does, forcing the identical synchronous `_rebuild_scrub_backdrop` on the very next paint. |
| E — GUI event-loop starvation | **Primary finding** | **High** | Same rebuild, same evidence as Issue 1's E. |
| F — Python GIL contention | Plausible contributing factor | Medium | Same reasoning as Issue 1. |

**Shared mechanism, not a coincidence**: both issues are two different *triggers*
(`bump_mark_backdrop_revision` for Mark, `_cancel_view_transform_gesture`/
`_finish_view_transform_gesture` for Zoom) for the same *consequence* — invalidating
`TimelineWidget._scrub_backdrop`, which forces one synchronous, GUI-thread,
Python-loop-heavy rebuild on the next paint. See §18 (Shared Root Cause Matrix).

---

## 13. Windows Title-Bar Analysis

Re-verified against the current code (not just the prior handoff's prose):

- **Mechanism** (established by the prior MTC fix, unchanged): a Windows top-level
  window's title-bar press-hold/drag enters `DefWindowProc`'s native, blocking
  `WM_SYSCOMMAND`/`WM_NCLBUTTONDOWN` modal move/resize loop, on the GUI thread, for
  every top-level window in the process (one shared GUI thread — both the main window
  and `CleanVideoOutputWindow` trigger it). Qt's event loop — and therefore every
  `QTimer` on that thread — does not run again until the interaction ends.
- **Audio / LTC survive**: confirmed unaffected — their sole scheduling mechanism is the
  PortAudio callback thread (§6/§7), which has no dependency on the GUI thread at all.
- **MTC survives**: confirmed unaffected — `_mtc_thread` (§8) is a plain
  `threading.Thread` paced by `Event.wait`, no Qt dependency. This is the prior fix,
  re-verified present and correct in the current code.
- **Main UI Timecode display freezes — proven, not assumed** (§9): every display
  consumer is downstream of `AudioEngine._poll`, a GUI-thread `QTimer`. It stops firing
  for the same reason `_mtc_timer` used to. **Because nothing downstream is an output**,
  this freeze is cosmetic: the underlying `AudioEngine.position` value is correct the
  entire time (it's driven by the PortAudio callback thread, not by `_poll`) — `_poll`
  merely stops *reading and displaying* it. When the drag ends and `_poll` resumes, the
  next tick reads the current (correct, unaffected) position and the display jumps
  straight to it — no backlog, no burst (there is nothing to replay; each tick reads a
  fresh absolute value, it does not accumulate deltas).
- **Clean Video Output freezes — proven, not assumed, and for two stacked reasons**
  (§10): (Reason A) its scheduling entry point (`video_sync.update_position`) is gated
  behind the identical frozen `_poll` chain, so no new frame is even requested during
  the drag; (Reason B) even a frame that had already finished decoding cannot reach the
  screen, because final presentation is an ordinary Qt `QWidget`/`QPainter` paint
  (`VideoPreviewWidget.paintEvent`) reached only via `QWidget.update()`'s posted-event
  mechanism, which itself requires the Qt event loop to be pumping. Reason B is a
  structural property of Qt's widget/paint model for a plain `QWidget`, not a scheduling
  choice — it would still apply even if Reason A were fixed by mirroring the MTC
  thread-based approach. This is the key architectural distinction from the MTC fix:
  MTC's real output is a raw MIDI byte send (no Qt paint step required at all), so moving
  its *pacing* off the GUI thread was sufficient by itself. Clean Video Output's real
  output (pixels on screen, for OBS Window Capture) is *inherently* a Qt paint operation
  for a plain `QWidget`-based surface — decoupling scheduling alone would not fully
  eliminate this issue's freeze, only its Reason-A component (no new frame requested).
  Fully eliminating Reason B would require a presentation mechanism not gated by the Qt
  event loop (e.g. a different widget/surface technology) — **explicitly not attempted
  or further explored in this diagnostic-only phase**; flagged as a question for the
  next phase's scoping (§21/§22).

---

## 14. Issue 1 Classification (Zoom)

See §11's table. **Primary: D (UI/presentation freeze) + E (GUI event-loop
starvation), High confidence.** Secondary/plausible: F (GIL contention), Medium
confidence, not confirmed by measurement. A/B/C not supported by any code-path evidence
found (High confidence against).

## 15. Issue 2 Classification (Mark creation)

See §12's table. **Primary: D + E, High confidence — same underlying mechanism as
Issue 1** (shared backdrop-cache invalidation → synchronous rebuild). Secondary: F,
Medium confidence. A/B/C not supported (High confidence against).

## 16. Issue 3 Classification (Clean Video Output title-bar freeze)

**D (video presentation freeze), High confidence**, via two distinct, stacked, fully
code-cited mechanisms (§10, §13): (Reason A) `video_sync.update_position()` scheduling
entry point gated behind the frozen GUI-thread `_poll`/`_on_position_changed` chain — the
same class of bug the MTC fix solved, unfixed here; (Reason B) final pixel presentation
is an inherent Qt `QWidget`/`QPainter` paint operation requiring the Qt event loop by
construction, independent of scheduling thread. Not A/B/C — nothing in the video
scheduling or presentation path touches `AudioEngine._lock`/`_position_frame`,
`MtcOutput`, or `MidiCueNotes` (High confidence against). This is **not** a
"display-only, no consequence" issue the way Issue 4 is: it has a real architectural
gap (Reason A) that is fixable by the same pattern already proven for MTC, plus a
harder structural constraint (Reason B) that is not.

## 17. Issue 4 Classification (Main UI TC display title-bar freeze)

**D (presentation-only freeze), High confidence.** Every consumer downstream of
`_poll`/`_on_position_changed` in this category (§9) only *reads* `AudioEngine.position`
and writes to display widgets; none of them write back into the playback clock, LTC, or
MTC state. The freeze is real (proven by the same `_poll`-suspension mechanism as the
old MTC bug) but has zero effect on anything actually sent externally or on the audible
program. Matches the task's own prior-session hypothesis, now confirmed with full
code-path citations rather than assumed.

---

## 18. Shared Root Cause Matrix

|                                 | Zoom (Issue 1) | Mark (Issue 2) | Title-Bar Video (Issue 3) | Title-Bar UI TC (Issue 4) |
|---------------------------------|:---:|:---:|:---:|:---:|
| GUI event-loop starvation (synchronous rebuild) | **X** (High) | **X** (High) | — | — |
| Windows native modal move/resize loop | — | — | **X** (High) | **X** (High) |
| `AudioEngine._poll` GUI-QTimer gating (same architectural class as the fixed MTC bug) | — | — | **X** (High — Reason A) | **X** (High) |
| Qt widget-paint-model hard dependency on GUI event loop (structural, not a scheduling bug) | (paint itself, same mechanism as D/E above) | (same) | **X** (High — Reason B, independent of Reason A) | (paint itself) |
| Python GIL contention | ~ (Medium, unconfirmed) | ~ (Medium, unconfirmed) | — (not applicable — presentation is Qt-loop-gated, not GIL-gated) | — |
| Playback clock / `AudioEngine._lock` involvement | No | No | No | No |
| LTC output involvement | No | No | No | No |
| MTC output involvement | No (direct); Low-Medium indirect via GIL | No (direct); Low-Medium indirect via GIL | No | No |
| Shared static-backdrop cache (`TimelineWidget._scrub_backdrop`) | **X** | **X** | — | — |
| Video decode lock / video-audio lock | No | No | No | No |
| Main-thread-only presentation (`QWidget`/`QPainter`) | N/A (Timeline is also a `QWidget`, same class of constraint for its own repaint, but not shared with Video) | N/A (same) | **X** | N/A (label/text widgets, same class of constraint but trivially cheap to repaint once the loop resumes) |

**Two genuinely distinct root-cause families, not one universal bug:**
1. **Family 1 — synchronous backdrop rebuild (Issues 1 & 2).** A `TimelineWidget`-local
   engineering cost: one expensive, GUI-thread, Python-loop-heavy rasterization
   triggered by cache invalidation. Fixable within `TimelineWidget` alone (e.g.
   incremental/async rebuild, further overscan reduction, moving the per-column loop to
   vectorized numpy, or spreading the rebuild across multiple frames) — does not require
   touching Playback Engine, LTC, MTC, or video code at all.
2. **Family 2 — GUI-thread-gated position fan-out during the Windows native modal loop
   (Issues 3 & 4).** The same architectural class as the already-fixed MTC bug, but for
   two different consumers of `AudioEngine._poll`. Issue 4 needs no fix (cosmetic only,
   matches design intent already accepted for other Qt apps' title-bar behavior). Issue 3
   has a real, fixable component (Reason A, same fix pattern as MTC) and a harder,
   structural component (Reason B, a genuine Qt widget-presentation constraint that would
   need a different design, not a quick thread swap).

These two families do not overlap in mechanism (one is CPU-cost-driven GUI-thread
occupancy; the other is OS-driven event-loop suspension), so a single unified fix is not
expected — this supports keeping them as separate fix phases (§21).

---

## 19. Unknowns

Everything below could not be settled by static reading alone and is called out
explicitly rather than guessed:

1. **Exact measured cost of `_rebuild_scrub_backdrop` on today's code** (post the 128 px
   overscan trim) — the 64-186 ms figure in the code comment predates that trim; the
   comment does not state a new post-trim number. Needs a live measurement (§20).
2. **Whether GIL contention during a `_rebuild_scrub_backdrop` call measurably delays
   `_mtc_thread`'s next `_mtc_tick()`, or the PortAudio callback's Python-side glue** —
   plausible from the architecture, not measured. Needs a new, small, purpose-built
   instrumentation probe (§20) since no existing counter tracks MTC-tick-to-tick wall
   interval.
3. **Whether an in-flight decoded video frame is actually dropped/coalesced (not
   presented as a queued burst) when a title-bar drag ends** — inferred from
   `video_sync.py`'s stale-frame-drop counters (`video.playback.frame_drop.reason.*`,
   `video.async_stale_drop`), not directly observed. Needs manual reproduction with
   `CUEPLAYER_PERF=1` (§20).
4. **`Cue Monitor.refresh_list()`'s actual cost** for a realistically large show (not
   measured this session) — architecturally decoupled from the mark-drop action via the
   debounce timer (§12), so unlikely to be the "instant Timecode drop" the user reports,
   but its own cost is unverified.
5. **Whether `video_sync.py`'s remaining ~4000 lines (not read in full this session —
   only the entry points relevant to Issues 3/4 were traced) contain any other
   GUI-thread-gated behavior relevant to scrub/land/resume paths** — out of scope for
   this diagnostic (the four reported issues concern engine-driven playback, not active
   scrubbing), but flagged in case a future session needs to extend this map to scrub
   behavior.
6. **`assign_main_cue_id_for_mark`'s exact cost** (`domain/main_cue_id.py`, not read this
   session) — presumed cheap/bounded by architecture (pure in-memory Cue-ID numbering,
   no Qt/paint/lock interaction reachable from its call site), not independently
   confirmed line-by-line.

---

## 20. Instrumentation Plan

**Most of what's needed already exists in this codebase** — `src/cueplayer/diagnostics/perf.py`,
enabled via the `CUEPLAYER_PERF=1` environment variable before launch. This is a
pre-existing, already-shipped, always-safe (no-op when disabled, "never call from the
PortAudio RT callback" is already respected by every call site audited in this session)
diagnostics framework — using it requires **no new code**, only running the existing
build with the env var set and reproducing each issue, then reading the dump.

### Step 1 — use the existing framework first (no new code)

1. Launch CuePlayer with `CUEPLAYER_PERF=1` set (PowerShell: `$env:CUEPLAYER_PERF=1;
   .\path\to\CuePlayer.exe`, or equivalent for a dev run).
2. Load a song with music + LTC + MTC (to a loopback/virtual MIDI port) + at least one
   Clean-Video-eligible Video Clip, and start playback.
3. **Reproduce Issue 1 (Zoom)**: scroll-wheel zoom in/out repeatedly for ~10 seconds.
4. **Reproduce Issue 2 (Mark)**: drop several Marks via keyboard shortcut while playing.
5. **Reproduce Issues 3/4 (title-bar)**: press-hold and drag the main window's title bar
   for a few seconds, then the Clean Video Output window's title bar, while playing.
6. Tools → **Write Performance Report** (`main_window.py:5674-5722`) — appends
   `perf_diag.report_text()` to `perf_diag.log_path()`
   (`%LOCALAPPDATA%\CuePlayer\cueplayer_perf.log` by default). Read the **last**
   `===== manual-dump =====` section only.
7. Key existing fields to read, already wired to exactly this diagnostic's questions:
   - `timeline.mark_backdrop.rebuild_ms` (span: n/mean/max) — the actual measured cost of
     every `_rebuild_scrub_backdrop` call this session, separated by `reason` via
     `timeline.mark_backdrop.rebuild_reason.<reason>` counters (`zoom_idle` vs
     `scrub_seed` vs `marks_ui_refresh` etc.) — this directly answers Unknown #1 and
     distinguishes the Zoom-gesture-end rebuild from the Mark-triggered rebuild.
   - `ui.event_loop_long_task_ms` (span) — every GUI-thread block that exceeded one frame
     budget (16.7 ms), from any source, not just the backdrop rebuild — a general
     "was the GUI thread ever stalled" signal.
   - `video.present_delayed_by_timeline_ms` (span) — already-instrumented, directly
     measures how long a ready video frame waited because `timeline.is_view_transform_busy()`
     was true — answers "does Zoom actually delay a real, already-decoded video frame."
   - `audio.callback.interval_max_s`, `audio.callback.deadline_miss_count`,
     `audio.callback.underflow_rate` (attrs, from `audio_callback_continuity()`) — the
     ground-truth check for whether the *actual audio/LTC output* (not just display) ever
     glitched during any of the four repro steps. If these stay flat/zero across a
     zoom/mark-drop session that otherwise shows a `timeline.mark_backdrop.rebuild_ms`
     spike, that is strong, already-available proof that A/B are correctly ruled out
     (not just architecturally implausible).
   - `video.async_stale_drop`, `video.playback.frame_drop.reason.*` counters — answers
     Unknown #3 (jump vs. burst on drag-release).
8. Tools → **Profile UI 5s** (`main_window.py:5724-5765`) — a stdlib `cProfile` capture
   of the GUI thread for a 5-second window, dumped as a cumulative-time top-40 to
   `cueplayer_ui_profile.txt`. Trigger this, then immediately perform several Zoom
   gestures or Mark drops within the 5-second window. If the hypothesis in §11 is
   correct, `_paint_waveform_peaks` / `_rebuild_scrub_backdrop` / `_paint_static_layers`
   should appear near the top of cumulative time — this would be direct, unambiguous
   confirmation (or refutation) of the per-pixel-column loop as the dominant cost,
   without writing a single line of new instrumentation code.

### Step 2 — one small new probe, only if Step 1 leaves the MTC-jitter question open (Unknown #2)

Static reading cannot prove or disprove whether a long GUI-thread rebuild measurably
delays the MTC thread's own tick cadence, because nothing currently records the MTC
thread's own tick-to-tick wall interval (only its *output* — quarter-frame sends — is
implicitly covered by external MIDI-monitor observation, which is a manual, not
automated, signal). If Step 1's data (specifically: audio callback continuity staying
clean while `timeline.mark_backdrop.rebuild_ms` spikes) is judged insufficient to close
this question, the minimal addition would be:

- **What to observe**: wall-clock interval between successive `_mtc_tick()` invocations
  on the `mtc-tick` thread.
- **Why existing code can't show this directly**: `_mtc_tick()`
  (`audio_engine.py:1343-1358`) has no timing instrumentation; `perf_diag.span`/`record_ms`
  are documented as UI-thread-or-worker-thread-only and are not currently called from
  this method, though the module's own docstring ("Never call from the PortAudio / real-time
  audio callback... Spans are UI-thread or worker-thread wall times only",
  `diagnostics/perf.py:9-13`) confirms a plain background thread like `mtc-tick` (not the
  RT audio callback) is an acceptable place to add one.
- **Where**: one `perf_diag.record_ms("mtc.tick_interval_ms", ...)` call inside
  `_mtc_thread_loop` (`audio_engine.py:1332-1341`), timing the gap between consecutive
  wake-ups (expected ~4 ms).
- **Clock**: `time.monotonic()` (already the convention used everywhere else in this
  file, e.g. `_pos_epoch_mono`, the PortAudio callback's `cb_t0`) — never wall-clock
  `time.time()`.
- **Does instrumentation risk disturbing the timing it measures?** Negligible — one
  `time.monotonic()` call and one dict append under `perf_diag`'s existing lock, matching
  the cost profile of every other `record_ms` call site already present in the hot paths
  audited this session (e.g. the PortAudio callback's own continuity probes,
  `audio_engine.py:2218-2264`, which the code's own comment states must add "no file I/O,
  no extra locks beyond the existing mix lock" — the proposed MTC probe follows the same
  discipline, and is gated behind `perf_diag.is_enabled()` exactly like every other call
  site, so it is a true zero-cost no-op when `CUEPLAYER_PERF` is unset).
- **How to compare expected vs. actual**: expected interval is 4 ms (the `Event.wait(0.004)`
  argument); `perf_diag`'s span summary already reports mean/max automatically — a max
  interval spiking above, say, 15-20 ms during a `timeline.mark_backdrop.rebuild_ms`
  window (correlated by timestamp/session) would be direct evidence of real GIL-driven
  MTC jitter; staying near 4-6 ms would rule it out.
- **This was NOT implemented in this session** — it is a proposed, minimal, clearly-scoped
  addition for a future instrumentation-only phase, per the task's explicit "diagnostic
  only" constraint. It touches only a background thread's own loop, calls only the
  already-audited, already-safe `perf_diag` API, and does not alter `_mtc_tick()`,
  `MtcOutput`, `MidiCueNotes`, or any timing/scheduling behavior.

### Manual reproduction matrix (for a human, on Windows, with a real or virtual MIDI port)

| Step | Action | What to watch |
|---|---|---|
| 1 | Load song (music + LTC + MTC to loopMIDI/Bome + ≥1 Video Clip), Play | Baseline: audio plays, MIDI monitor shows quarter frames, Clean Video shows picture |
| 2 | Wheel-zoom rapidly in/out for ~10s | Does the on-screen TC visibly stutter? Does the MIDI monitor show any gap? Does audio glitch audibly? |
| 3 | Drop 5-10 Marks via shortcut while playing | Same three questions as step 2 |
| 4 | Press-hold main window title bar 3-5s, release | Confirm: audio/MTC continuous (already proven); Clean Video freezes then snaps to current position (not a slow catch-up); UI TC freezes then jumps |
| 5 | Repeat step 4 dragging the title bar instead of holding | Same as step 4 |
| 6 | Repeat steps 4-5 on the Clean Video Output window's title bar | Same as step 4 |
| 7 | Tools → Write Performance Report after each of steps 2-6 | Correlate `timeline.mark_backdrop.rebuild_ms`, `ui.event_loop_long_task_ms`, `video.present_delayed_by_timeline_ms`, `audio.callback.*` against what was subjectively observed |

---

## 21. Recommended Fix Phases

Given §18's two-family split, the previously-envisioned split (Phase B: Zoom/Mark;
Phase C: Video freeze; Phase D: UI TC freeze) is **directionally correct and is
confirmed by this audit**, with one refinement: Phase D is now known (High confidence)
to need **no code change at all** — it is working as an inherent, harmless consequence
of Qt's title-bar behavior, matching every other Qt/Windows application. Recommend either
dropping Phase D or narrowing it to "confirm with the user that no fix is wanted /
document as known, accepted behavior," rather than treating it as an open bug.

- **Phase B — Timeline static-backdrop rebuild cost** (Issues 1 & 2, Family 1). Scope:
  `TimelineWidget._rebuild_scrub_backdrop` / `_paint_waveform_peaks` and related static
  paint helpers only. Candidate directions (not decided/scoped here — this is a
  diagnostic phase): reduce/eliminate the per-pixel-column pure-Python loop (e.g. a
  vectorized numpy line-segment build), split the rebuild across multiple frames/idle
  callbacks instead of one synchronous call, or further reduce overscan for the
  `marks_ui_refresh`/`scrub_seed` reasons the way `zoom_idle` already was. Needs the
  Step-1 instrumentation data first to confirm today's actual cost (post the prior
  overscan trim) before deciding whether this is still worth the engineering effort.
- **Phase C — Clean Video Output title-bar freeze, Reason A only** (Issue 3's fixable
  component). Scope: decouple `video_sync.update_position()`'s *trigger* from
  `AudioEngine._poll` during a title-bar drag — e.g. mirroring the MTC fix's pattern
  (a background-paced trigger independent of the Qt event loop) so scheduling requests
  keep flowing even while presentation is necessarily still queued behind the modal
  loop. This would at minimum ensure the *first* frame after drag-release is already
  decoded and ready to present the instant the event loop resumes, rather than only then
  starting to decode it — reducing (not eliminating, per Reason B) the visible freeze
  duration. Needs explicit scoping/design discussion before implementation, since it
  touches `VideoSyncController`'s state machine, which `AGENTS.md` and this audit both
  note is large and not fully read this session.
- **Not recommended as a phase**: attempting to solve Issue 3's Reason B (presentation
  itself being Qt-event-loop-gated) is a materially larger architecture question (a
  different rendering/presentation technology for `CleanVideoOutputWindow`) that was
  explicitly out of scope for this diagnostic session and should be raised with the user
  as a separate, larger discussion if the residual freeze duration after a Phase C fix is
  still unacceptable for live show use — not silently folded into Phase C.
- **Phase D — drop or reclassify as "confirmed working as intended."**

---

## 22. Regression Risks

Not applicable in the sense of "risk from this session's changes" — **no production code
was changed**. Forward-looking risks for whoever implements Phase B/C next, noted here
so that phase's own diagnosis doesn't have to be redone:

- **Phase B risk**: `_rebuild_scrub_backdrop` is shared by Zoom, Mark creation, scrub,
  and ordinary scroll/resize (`timeline_widget.py`'s many `reason=` call sites) — any
  change here needs to be verified against all of those triggers, not just Zoom/Mark, to
  avoid trading one hitch for a correctness regression (e.g. stale backdrop content) in
  an untested trigger path. The existing `timeline.mark_backdrop.rebuild_reason.<reason>`
  counters are a good regression-test hook (assert cache-hit/miss counts don't change
  unexpectedly for unrelated interactions).
- **Phase C risk**: any change to `video_sync.update_position`'s trigger must preserve
  the existing scrub/land/resume gating logic (`main_window.py:5361` guards on
  `engine_video_gated()`) — this audit did not fully read `VideoSyncController`'s ~4200
  lines, so a future implementer must re-verify those gates are not accidentally bypassed
  by whatever new trigger mechanism is chosen.
- **Test safety reminder** (carried over from `.ai/NEXT_TASK.md`, still true): do not run
  a full unfiltered `tests/ui/` sweep — several pre-existing tests spawn a real
  `video_waveform_worker` subprocess that can hang on garbage input.

---

## 23. Manual Reproduction Matrix

See §20's table (kept in one place to avoid duplication).

---

## Files read this session (for traceability)

`src/cueplayer/playback/audio_engine.py` (full), `src/cueplayer/playback/mtc_output.py`
(full), `src/cueplayer/playback/midi_cue_notes.py` (full),
`src/cueplayer/ui/video_output_window.py` (full), `src/cueplayer/ui/video_preview.py`
(full), `src/cueplayer/diagnostics/perf.py` (full), targeted sections of
`src/cueplayer/ui/timeline_widget.py` (zoom: wheelEvent, set_zoom, zoom_by,
_begin/_finish/_cancel_view_transform_gesture, _rebuild_scrub_backdrop,
_bake_mark_annotation_sprites, _invalidate_scrub_backdrop, _blit_native_backdrop,
_blit_native_pixmap, _can_use_static_backdrop, paintEvent, _paint_waveform_peaks;
mark-related: bump_mark_backdrop_revision), targeted sections of
`src/cueplayer/ui/main_window.py` (_on_position_changed, _on_video_frame,
_refresh_output_timecode_clock, _add_mark, _add_mark_by_shortcut, _refresh_marks_ui,
_schedule_cue_list_refresh, _setup_autosave/_autosave_tick, _profile_ui_5s,
Write-Performance-Report handler, video_sync wiring), targeted sections of
`src/cueplayer/playback/video_sync.py` (class header/timer inventory, update_position,
frame_changed emit site), `src/cueplayer/domain/undo.py` (AddMarksCommand /
DeleteMarksCommand), targeted sections of `src/cueplayer/domain/models.py` (add_mark,
sort_marks), full-repo `Grep` sweep for `QTimer(`/`threading.Thread(`/`QThread`/
`ThreadPoolExecutor(`/`threading.Lock(`/`threading.RLock(`/`threading.Event(` across
`src/cueplayer/`. Also read `.ai/handoffs/2026-09-07_MtcTitleBarStallFix.md` (prior MTC
fix, re-verified against current code, not taken on faith).
