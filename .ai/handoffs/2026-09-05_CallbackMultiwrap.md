# Audio callback multi-wrap loops

Date: 2026-09-05. Branch: `cursor/technical-audit-0815-028d`.

## Task objective
Correct H05 when one callback spans multiple loop repetitions.

## What was implemented
Use bounded contiguous segments for Music/LTC/video chunks, modulo next-frame
bookkeeping (including exact B boundary) and identical loop handling for direct
File-LTC routing. No out-of-loop PCM tail is read for later repetitions.

## Files changed
`playback/audio_engine.py`, `tests/playback/test_callback_multiwrap.py`, AI docs.

## Architecture decisions
Keep existing loop engage rules and one sample clock. No MTC scheduler change
in this slice. No zero-allocation claim: existing numpy mix allocations remain.

## Tests performed
Before fix 9 failed/3 passed. Expanded suite after fix: 62 passed in 2.32s.
Includes 44.1/48/96k, 20/64/1024/4096-frame blocks, exact boundary, direct File-LTC
route, synthetic LTC/video segment readers, rate/clock diagnostics regressions.

## Remaining issues
MTC natural loop reset and UI timer bursts still need work. LTC receiver relock
is untested; calibration click handling is separate from looped program media.
Public DAC clock, ASIO hardware and historical native/UI failures remain open.

## Suggested next task
Bound MTC catch-up and explicitly reset on natural loop discontinuity without
sending MIDI from the audio callback. Test fake port behavior before hardware.
