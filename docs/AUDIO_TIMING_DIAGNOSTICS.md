# Audio timing diagnostics (Phase 0)

Opt-in observations only: these do not fix write-head/presentation timing or
rate negotiation. Run the source checkout with:

```powershell
$env:CUEPLAYER_AUDIO_TRACE = '1'
$env:CUEPLAYER_PERF = '1'
$env:CUEPLAYER_PERF_LOG = "$env:TEMP/cueplayer-audio-perf.txt"
.venv/Scripts/python.exe -m cueplayer
```

Existing PERF reports include `audio.timing` when the continuity report is
published. For a programmatic non-RT inspection, call
`engine.audio_timing_diagnostics()`. Read before closing the engine. There is
no new UI, auto-upload or callback disk write.

The ring holds the latest 512 callbacks, so its time span depends on blocksize.
At 48k/480 frames it contains about 5.12 seconds; at 48k/64 about 0.68 seconds.
Take a snapshot promptly after an event. It is not an entire-show recording.
Concurrent snapshots skip overwritten rows instead of locking the callback.
The ring has 15 float64 fields per row (61,440 bytes payload). Python scalar
operations still cost interpreter time; compare tracing on/off in hardware tests.

Fields distinguish callback-requested, engine-processing and source rates.
`stream_reported` reads samplerate/latency/active/closed on the reporting thread;
these do not measure the hardware oscillator. Stream epoch counts open attempts,
including failed attempts. Transport generation currently identifies seeks;
natural loop wraps can be inferred from frame discontinuities but do not yet
publish a full transport-generation contract.

`current_time` and `dac_time` use the PortAudio time base. `host_monotonic` uses
Python monotonic; do not subtract them without establishing a clock bridge.
Unavailable timestamps are NaN; a valid-looking driver timestamp is not yet
independently verified. `start_frame` and `end_frame` describe write bookkeeping,
not audible position. A wrapped block cannot be reconstructed as one straight
interval from those two values; future clock work must publish its segments.

Reason codes: 0 render, 1 paused, 2 caught mix exception, 3 music resample PCM
unavailable, 4 end-of-media. These are render states, NOT an assertion that all
output channels are silent: video/LTC can remain active. Exception type/text is
not formatted in the callback. Raw-source ready intervals remain explicitly
unknown because the current AudioBuffer does not expose them.

Unit tests use a non-callback fake OutputStream and retain/clean up engine and
video-controller objects. Native codec tests still use PyAV. This is not an
ASIO integration test environment. Full-suite native/GUI failures remain under
investigation; do not treat the passing focused suite as release certification.
