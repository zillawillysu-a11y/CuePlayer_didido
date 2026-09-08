# MTC discontinuity recovery

Date: 2026-09-05. Branch: `cursor/technical-audit-0815-028d`.

## Task objective
Recover MTC after natural loops and bound stale quarter-frame catch-up.

## What was implemented
Backward targets or more than eight overdue QFs re-anchor with full-frame plus
current QF instead of waiting/bursting. Audio callback increments loop sequence;
UI MTC tick observes and resets even if the new loop position is numerically
higher. No MIDI I/O added to the audio callback. Enabled MTC with no selected
port now returns the existing explicit error rather than silently succeeding.

## Files changed
`playback/audio_engine.py`, `playback/mtc_output.py`,
`tests/playback/test_mtc_discontinuity.py`, MTC backend tests,
`docs/AUDIO_TIMING_DIAGNOSTICS.md`, AI report/handoff pointers.

## Architecture decisions
This is bounded recovery, not the independent deadline scheduler proposed by
the audit. MTC still depends on UI ticks and raw/write-head time. Existing MIDI
cue-note boundary behavior is unchanged and still needs work. Keep one clock,
single audio device/free routing, Unicode, multi-version and MA conventions.

## Tests performed
Three new tests failed before fix, including 10,801 messages on a long stall.
After fixes: 63 passed in 4.64s across MTC/backend/file mirror/toggles/MIDI notes,
multi-wrap, rate transaction and clock diagnostics. Stale backend test configure
calls updated to explicitly enable midi_master. No external receiver validated.

## Remaining issues
Affected ASIO driver/interface still unconfirmed (machine lists ASIO4ALL v2 and
Realtek ASIO, no Focusrite). Physical pitch/DAC/LTC/MTC receiver tests pending.
Public playhead remains legacy; new DAC result is a diagnostic shadow only.
Full-suite native/UI failures, streaming/RAM, atomic save, NDI shutdown, fractional
FPS/DF, stereo phase cancellation and Theatre implementation remain open.

## Suggested next task
Obtain affected ASIO driver/interface and a diagnostic report during playback;
validate hardware timestamp quality before changing public presentation clock.
Independent remaining fixes should stay separate, with the full-suite failure
baseline explicitly retained. See technical audit and diagnostics instructions.
