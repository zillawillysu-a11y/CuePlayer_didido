# Company Focusrite ASIO checks — 2026-09-06

Source baseline: `4915f2e`, local branch `technical-audit-0815-028d`, tracking
`origin/cursor/technical-audit-0815-028d`. Live fetch confirmed no newer upstream.
Created local Python 3.13.14 `.venv` with the project's development dependencies.

Windows reports connected Focusrite USB Audio/MIDI. PortAudio exposes exactly
one ASIO device here: **Focusrite USB ASIO**, 6 inputs / 4 outputs. The interface
model and whether this is the interface used for the original symptom are still
unconfirmed. Installed driver registry entries alone are not connected devices.

## Silent driver measurements

Both JSON files contain native output callback observations, not AudioEngine
playback or a hardware loopback. All four output channels received zero samples.
No input recording, music, LTC or MIDI was performed. Each stream was closed.

| Measurement | 5-second run | 10-second repeat |
| --- | ---: | ---: |
| Requested / stream-reported sample rate | 44100 / 44100 Hz | 44100 / 44100 Hz |
| Callback block size | 1024 frames | 1024 frames |
| Callbacks | 214 | 431 |
| Callbacks reporting status flags | 0 | 0 |
| Reported output latency | 49.864 ms | 49.864 ms |
| Maximum absolute DAC interval residual | 22.491 ms | 22.909 ms |

Residual = consecutive DAC timestamp difference minus previous block duration.
The repeated nonuniform intervals warrant examination in real playback; they
do not establish an audible dropout, oscillator error or a driver defect. In
particular, zero reported status flags does not prove gapless physical output.
The constant DAC-current delta equals the reported latency and is not an
independent measurement of physical output latency. Do not automatically apply
49.864 ms as a UI offset or promote the DAC shadow to the public clock.

Reproduce with a fresh report filename:

```powershell
.venv/Scripts/python.exe scripts/asio_timing_probe.py --device 'Focusrite USB ASIO' --seconds 5 --output .cache/asio-new.json
```

The standalone probe uses a bounded callback trace and opens only an exactly
matched ASIO device at its enumerated default rate. It refuses existing report
paths. It does not edit application preferences or projects.

## Regression checks

44 passed in 3.77s:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv/Scripts/python.exe -m pytest -q tests/playback/test_audio_timing_diagnostics.py tests/playback/test_stream_rate_transaction.py tests/playback/test_callback_multiwrap.py tests/playback/test_mtc_discontinuity.py tests/playback/test_mtc_midi_backend.py tests/playback/test_mtc_mirrors_file_ltc.py tests/playback/test_mtc_requires_toggle.py --disable-warnings --tb=short
```

These tests use the repository's fake streams, not ASIO. Historical full-suite
failures remain open. Probe JSON records Python, PortAudio and relevant package
versions; this is not a packaged EXE validation.

## Next: capture the affected playback

Run `scripts/start_audio_diagnostics.ps1` from normal PowerShell (or Codex with
execution approval). Open the affected project, select Focusrite USB ASIO in
Audio settings, and play the material that showed the symptom. During playback,
use Tools → Write Performance Report promptly after seek/loop or the symptom.
Logs are local under `.cache/audio-diagnostics/`; do not commit user media.

Need the project/media path and interface model from the user. Compare actual
AudioEngine trace, UI position, stream rates and DAC shadow before any clock
change. Physical timing/pitch still needs known loopback/receiver setup.
