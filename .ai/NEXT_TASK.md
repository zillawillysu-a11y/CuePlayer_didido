# Next task

Capture Tools → Write Performance Report during affected Focusrite USB ASIO
playback (including seek/loop), then analyze rate consistency and DAC shadow
against legacy UI timing. Confirm interface model and physical loopback setup
before promoting any presentation-clock correction.

Company hardware now exposes Focusrite USB ASIO, 6 in / 4 out. Silent 5/10-second
checks: 44100 Hz, 1024 frames, reported 49.864 ms latency, no status flags,
but nonuniform DAC intervals. Not physical timing or symptom certification.
Source GUI launched with diagnostics; affected playback report still pending.
See docs/audit/2026-09-06/README.md and the company Focusrite handoff.

Software slices committed: diagnostics, stream-rate consistency/failure recovery,
DAC shadow, waveform LOD/tail/zoom, video waveform batch carry, callback multiwrap,
bounded MTC discontinuity recovery. No claim that all audit phases are complete.
See .ai/REPORT.md, CUEPLAYER_TECHNICAL_AUDIT.md and docs/AUDIO_TIMING_DIAGNOSTICS.md.
