# Timing Architecture Diagnostic (Zoom / Mark / Title-Bar Timecode Drop)

Date: 2026-09-07. Branch: `technical-audit-0815-028d`. Status: **diagnostic only —
no production code changed.**

## Task objective

Show-critical diagnostic-only audit (explicitly no fixes this session) of CuePlayer's
timing architecture — Playback Clock, Audio, LTC, MTC, Main UI Timecode display, Clean
Video Output, Timeline interaction, Qt GUI thread, background workers — to build an
execution/ownership/dependency map and classify four reported symptoms:

1. Occasional Timecode drop while zooming the Timeline with the mouse wheel.
2. Occasional Timecode drop while creating/dropping a Mark.
3. Clean Video Output freezes while the Windows title bar (main window or Clean Video
   Output window) is held/dragged.
4. Main UI Timecode display freezes during the same title-bar hold/drag.

Full 23-section detail: `.ai/handoffs/2026-09-07_TimingArchitectureDiagnostic.md`.

## What was implemented

Nothing in production code. Five parallel static-audit passes (independently reading
`audio_engine.py`, `mtc_output.py`, `midi_cue_notes.py`, `video_sync.py`,
`video_output_window.py`, `video_preview.py`, `timeline_widget.py`, `main_window.py`,
`domain/models.py`, `domain/undo.py`, `cue_monitor_panel.py`, and a repo-wide
QTimer/Thread/Lock inventory) were cross-checked against each other and against direct
spot-re-reads of the load-bearing citations (all confirmed accurate: `_poll` QTimer at
16 ms, the `_rebuild_scrub_backdrop` 64–186 ms hitch comment, `_async_frame_ready`'s
`QueuedConnection`, `_mtc_thread`'s daemon-thread design, `_silent_timer`, `Song.add_mark`).
Findings converged into one consolidated handoff document with the Architecture Map,
Thread Ownership Map, Timer Inventory, per-subsystem path traces, Zoom and Mark
execution traces, Windows title-bar analysis, per-issue classification tables, a Shared
Root Cause Matrix, Unknowns, and an Instrumentation Plan.

## Files changed

- `.ai/handoffs/2026-09-07_TimingArchitectureDiagnostic.md` (new) — full diagnostic.
- `.ai/REPORT.md` (this file).
- `.ai/NEXT_TASK.md` — points to this diagnostic's recommended next phases.

No `src/cueplayer/` file was modified.

## Architecture decisions

None made this session (diagnostic only). Key architecture facts **confirmed** (not
decided) by this audit:

- `AudioEngine._position_frame` (`audio_engine.py:107`) remains the single playback
  clock, advanced only inside the PortAudio native callback thread under
  `AudioEngine._lock` — unchanged, and the correct design per `AGENTS.md`/`WORKFLOW.md`'s
  "AudioEngine sample position remains the only playback clock" rule.
- LTC is not a separate clock: it is an array slice rendered into the *same* buffer as
  music, in the *same* PortAudio callback (`audio_engine.py:2140-2178`).
- MTC's own timing bug (GUI-`QTimer`-paced, frozen by the Windows title-bar modal loop)
  was already fixed in a prior session (`.ai/handoffs/2026-09-07_MtcTitleBarStallFix.md`)
  via a dedicated daemon thread — re-verified present and correct in the current code.
- **New finding this session**: the *same* architectural bug class the MTC fix solved
  is still present, unfixed, for two other consumers of the same `AudioEngine._poll`
  GUI-thread `QTimer` — the Main UI Timecode display (cosmetic only, no real-output
  consequence — High confidence) and Clean Video Output's frame-scheduling entry point
  (`video_sync.update_position`), which for Clean Video Output is a real, fixable gap
  layered under a second, harder, structural Qt-widget-paint constraint that a simple
  thread swap cannot fully solve. See handoff §10/§13/§16.
- **New finding this session**: Zoom and Mark creation share one confirmed root cause —
  both invalidate `TimelineWidget._scrub_backdrop`, forcing a synchronous, GUI-thread,
  measured-64–186 ms full backdrop rebake (`_rebuild_scrub_backdrop`,
  `timeline_widget.py:3242-3329`) on the next paint. This is a UI/presentation-layer
  stall (classifications D + E), not a Playback/LTC/MTC output discontinuity — no code
  path in either trace touches `AudioEngine._lock`/`_position_frame`/`MtcOutput`/
  `MidiCueNotes`. See handoff §11/§12/§18.
- Two genuinely distinct root-cause families, not one unified bug: Family 1 (Zoom +
  Mark) is GUI-thread CPU-cost-driven; Family 2 (title-bar Video + UI TC) is
  OS-modal-loop-driven event-loop suspension. Recommend keeping them as separate fix
  phases.

## Tests performed

None — diagnostic-only session, no production code touched. All findings are static
code reads, cross-verified across independent audit passes and, in the key cases,
directly re-confirmed by grep/read against the current file contents by the session
coordinator.

## Remaining issues

Everything is `UNKNOWN — NEEDS INSTRUMENTATION` rather than fixed; see handoff §19/§20
for the full list and the proposed (not-yet-implemented) minimal instrumentation plan.
Highlights:

- Exact current (post-overscan-trim) cost of `_rebuild_scrub_backdrop` is not measured
  in this session — the 64–186 ms figure in the code's own comment predates a later
  overscan reduction.
- Whether GUI-thread GIL hold during that rebuild measurably delays the MTC thread's own
  tick cadence or the PortAudio callback's Python-side glue is architecturally plausible
  but not measured — CuePlayer already has a `CUEPLAYER_PERF=1` instrumentation
  framework (`src/cueplayer/diagnostics/perf.py`) that covers almost all of this without
  writing new code; one small proposed addition (`mtc.tick_interval_ms`) would close the
  one real gap.
- A real but benign, unaddressed race: `MidiCueNotes`'s background-thread scan of
  `song.marks` (every 4 ms) shares no lock with `Song.add_mark`'s GUI-thread
  append+sort — cannot corrupt memory under the GIL, but is architecture debt worth a
  proper lock in a future session (not a cause of any of the four reported symptoms).

## Suggested next task

See `.ai/NEXT_TASK.md`. In short: **Phase B** (Timeline static-backdrop rebuild cost —
Zoom/Mark, Family 1) and **Phase C** (Clean Video Output title-bar freeze, Reason A
only — decouple `video_sync.update_position`'s trigger from `AudioEngine._poll`,
mirroring the MTC fix). Phase D (Main UI TC display title-bar freeze) is recommended to
be **dropped or reclassified as confirmed-working-as-intended**, not treated as an open
bug — High confidence, fully code-cited, zero real-output consequence. Do not start any
fix phase until the user reviews this diagnostic and explicitly requests it.
