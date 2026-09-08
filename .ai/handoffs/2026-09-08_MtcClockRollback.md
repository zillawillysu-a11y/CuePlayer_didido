# MTC callback-clock rollback regression — candidate fix

Date: 2026-09-08
Branch: `cursor/mtc-clock-rollback-028d`
Base: `cd8c35a1fbb9bc1c6956e7cb638c11267011c70c` on `technical-audit-0815-028d`.

## Task objective

Investigate the user's continuing DirectSound MTC receiver dropouts after the
recent LTC clip changes and scheduler fix; correct a reproducible protocol
regression and deliver a hardware-testable candidate with useful diagnostics.

## What was implemented

`4915f2e` added `target < _last_qf_index` as an implicit seek trigger in
`MtcOutput.tick`. The 1.1.3 baseline did not have that trigger. AudioEngine's
`raw_position` extrapolates its write-head using elapsed monotonic time and
re-stamps it after each callback. Delayed/bunched callbacks can therefore
produce a backwards position estimate even while sample heads advance.
The new trigger sent a Full Frame SysEx and repeated QF pieces in that case.

A second deterministic failure uses an LTC clip boundary: the existing code
intentionally skips to the end of a QF group that straddles two clip mappings.
Its cursor is then ahead of the current position; the same backward test
mistook that deliberate skip for a seek, producing repeated locates until the
next group. This requires no clock rollback at all.

The fix removes the implicit backward-locate condition. The sender keeps its
QF cursor until the sample clock catches up; explicit `on_seek` notifications
still reset immediately, including 1 ms seeks, natural loops and source changes.
The forward backlog limit (>8 QFs) remains. No new clock, buffer setting,
LTC renderer, UI timer, MIDI backend or audio callback behavior was introduced.

Sender-side PERF diagnostics now expose successful QF count, QF send-start gap
mean/max, MIDI send errors, observed backward position count/max, and Full Frame
counts by play / seek_or_source / resume / overdue / clip_boundary reason.
Existing AudioEngine report aggregation automatically publishes these fields.
Counters are bounded aggregates; no per-message file I/O. QF interval history
is cleared on explicit seek/play/pause so intentional silence is not treated
as a running-cadence gap. A new sender resets the report, so the startup Full
Frame can occur before the measurement window and `full_frame_play_count=0`
is not itself an error.

The previous report's proposed 250 Hz/GIL mechanism is not established by
these tests. Lower wake frequency alone does not fix the protocol failures
reproduced against its candidate `cd8c35a`. These synthetic timings are not
claimed as a recording of the user's DirectSound device.

## Files changed

- `src/cueplayer/playback/mtc_output.py`
- `tests/playback/test_mtc_clock_rollback.py`
- `tests/playback/test_audio_mtc_timing_reliability.py`
- `tests/playback/test_mtc_discontinuity.py`
- `.ai/REPORT.md`, this archived handoff, `.ai/NEXT_TASK.md`

## Architecture decisions

AudioEngine remains the sample-clock master. Real transport discontinuities
must call `MtcOutput.on_seek`; AudioEngine already does so for seek/loop/source
changes. A lower interpolated value is not a transport command. The existing
backward-jump unit test now invokes that explicit notification instead of
requiring the erroneous implicit behavior. GUI-independent scheduling and
existing LTC clip half-open mapping/silence remain in place.

## Tests performed

- Before fix: four isolated callback-position-correction cases failed at
  24/25/29.97/30 fps (unexpected SysEx/repeated pieces).
- Baseline comparison: loaded the unmodified `cd8c35a` MtcOutput in memory,
  retaining the actual current AudioEngine callback/clock and new tests.
  Four jittered callback integration cases plus one clip group-skip test:
  **5 failed**. No production file was replaced for this comparison.
- Candidate: focused MTC scheduler/lifecycle, callback timing, clip playback,
  GUI stall independence, file-LTC mirror, MIDI toggle/backend and entire
  `tests/timecode`: **123 passed**.
- The integration fixture alternates 25/3 ms callback arrivals writing 14 ms
  of samples each. It checks increasing sample heads, a genuinely regressing
  raw position, no unexpected SysEx, exact QF piece order/count and no MIDI
  send under the audio lock. It does not emulate Windows driver behavior.
- `git diff --check`: passed.
- Tests ran under Linux/Python 3.12 with real Python dependencies and local
  native PortAudio/Qt dependencies; repo fixtures replace hardware streams.
  Windows EXE packaging and receiver verification were not performed.

## Remaining issues

The user explicitly authorized publishing this candidate to the supplied
GitHub repository on 2026-09-08. Delivery uses an independent candidate branch
and draft PR targeting `technical-audit-0815-028d`. Windows receiver validation
is still required before considering the hardware issue resolved.

This is a regression fix with reproducible evidence, not a confirmed resolution
of the user's hardware outcome. It does not make `raw_position` monotonic or
eliminate callback scheduling jitter, stalls, QF batching, or receiver latency.
Raw-position oscillation across a clip boundary may still trigger the engine's
explicit source-change path; the new `full_frame_seek_or_source_count` helps
identify that distinct path. Driver errors or continuing `overdue` re-anchors
need actual capture, not an assumed GIL diagnosis.

Use the same Song, MIDI endpoint and receiver with DirectSound and ASIO. Record
whether only the receiver drops or music also stutters. Compare continuous
playback away from clip edges and a separate clip-boundary/seek/loop trial.
The sender metrics measure calls to the MIDI driver, not receiver arrival.

## Suggested next task

On Windows, test this branch from source using
`.\scripts\start_audio_diagnostics.ps1` (existing `.venv` required).
Play the failing Song with DirectSound/MTC ON for 30 seconds without moving the
playhead, then **while still playing** choose Tools > Write Performance Report.
Repeat with ASIO and retain the two manual-dump sections. Separately test
seek, A-B loop, adjacent clips/gaps, and title-bar dragging. If fixed, rebuild
with `packaging/build_windows.ps1`; if not, compare `mtc.*` QF gaps, backward
counts, Full Frame reasons, send errors and audio callback timing before
changing another mechanism. Do not call this hardware-resolved until tested.
