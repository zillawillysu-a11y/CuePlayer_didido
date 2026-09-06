# Company Focusrite ASIO diagnostics
Date: 2026-09-06. Branch: technical-audit-0815-028d.
Upstream: origin/cursor/technical-audit-0815-028d.

## Task objective
Resume yesterday's pending ASIO verification on the company computer.

## What was implemented
Confirmed live upstream 4915f2e. Created Python 3.13.14 .venv; all pinned packages
match yesterday's dependencies.txt (editable checkout path differs).
Confirmed connected Focusrite USB Audio/MIDI, ASIO 6 inputs / 4 outputs.
Added silent driver probe, raw evidence and diagnostic launcher.
Source GUI started with AUDIO_TRACE/PERF; log confirms visible main window.
Actual affected playback report is pending.

## Files changed
scripts/asio_timing_probe.py; scripts/start_audio_diagnostics.ps1;
docs/audit/2026-09-06/README.md and two JSON traces;
docs/AUDIO_TIMING_DIAGNOSTICS.md; AI report, next-task and this handoff.

## Architecture decisions
No production playback change. One ASIO stream, silence on four outputs,
no input capture or MIDI/LTC. Driver timestamps are not physical latency.
Keep DAC shadow diagnostic. AudioEngine remains sole clock; Unicode,
multi-version audio, routing, shared video and MA export constraints remain.

## Tests performed
44 passed in 3.77s across timing, rate transaction, multiwrap and MTC tests.
Real ASIO 5/10-second runs: 44100 Hz, 1024 frames, 214/431 callbacks, no status
flags; reported latency 49.864 ms. Maximum absolute adjacent DAC interval
residual 22.491/22.909 ms. Both streams closed and strict JSON traces saved.
Nonuniform intervals repeat but do not establish audible dropout/driver defect.
GUI startup succeeded; git diff --check before commit.

## Remaining issues
Interface model, affected material, symptom reproduction and actual AudioEngine
trace still pending. Physical loopback/pitch/LTC/MTC verification not done.
Historical full-suite failures remain; focused passing tests are not release
certification. No public clock change.

## Suggested next task
Capture Tools → Write Performance Report during affected Focusrite USB ASIO
playback (including seek/loop), then analyze rate consistency and DAC shadow
against legacy UI timing. Confirm interface model and physical loopback setup
before promoting any presentation-clock correction.
See docs/audit/2026-09-06/README.md and docs/AUDIO_TIMING_DIAGNOSTICS.md.
