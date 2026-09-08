# DAC presentation shadow

Date: 2026-09-05. Branch: `cursor/technical-audit-0815-028d`.

## Task objective
Build a diagnostic DAC-position comparison before changing public playhead timing.

## What was implemented
Use recorded callback intervals and PortAudio stream time to estimate the
currently scheduled sample. Preserve queued pre-seek generation; reject invalid,
missing, underflow, inactive and non-linear/partial data instead of guessing.
Report alongside legacy UI position using existing Tools performance report.

## Files changed
`diagnostics/audio_timing.py`, `playback/audio_engine.py`,
`tests/playback/test_dac_presentation_shadow.py`,
`docs/AUDIO_TIMING_DIAGNOSTICS.md`, AI report/handoff pointers.

## Architecture decisions
Diagnostic-only; no Timeline clock switch or manual offset. No new callback
allocation beyond the prior opt-in trace. Physical DAC timestamp quality must
still be measured. Existing product/clock/routing constraints remain.

## Tests performed
85 passed in 1.60s across shadow/timing/rate-transaction/device/device-rate/loop/
source-LTC/video-mix suites. Includes 44.1/48/96k and queued seek boundaries.
Read-only device enumeration found ASIO4ALL v2 and Realtek ASIO, no Focusrite.
No hardware stream was opened for that enumeration.

## Remaining issues
User's affected ASIO driver/interface is still unspecified. Question pending;
user requested continuing independent work. No actual ASIO pitch or physical
DAC validation. Historical full-suite native/UI failures remain unresolved.
H01 is not yet a public playhead fix; loops need a proper render segment map.

## Suggested next task
Fix independently reproduced waveform LOD selection and partial tail buckets,
with rate/impulse/viewport regression tests. Keep playback PCM unchanged.
ASIO hardware confirmation remains a separate pending item.
