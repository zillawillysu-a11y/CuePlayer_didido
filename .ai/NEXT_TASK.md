# Next task

Confirm the affected ASIO driver/interface and capture Tools → Write Performance
Report during playback with CUEPLAYER_AUDIO_TRACE=1 and CUEPLAYER_PERF=1.
Validate DAC timestamps/loopback before switching the public presentation clock.
Current enumeration: ASIO4ALL v2, Realtek ASIO; no Focusrite. Do not infer which
one caused the user's symptom. Hardware clarification remains unanswered.

Software slices committed: diagnostics, stream-rate consistency/failure recovery,
DAC shadow, waveform LOD/tail/zoom, video waveform batch carry, callback multiwrap,
bounded MTC discontinuity recovery. No claim that all audit phases are complete.
See .ai/REPORT.md, CUEPLAYER_TECHNICAL_AUDIT.md and docs/AUDIO_TIMING_DIAGNOSTICS.md.
