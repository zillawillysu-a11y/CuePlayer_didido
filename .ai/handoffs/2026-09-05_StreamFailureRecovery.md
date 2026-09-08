# Stream failure recovery

Date: 2026-09-05. Branch: `cursor/technical-audit-0815-028d`.

## Task objective
Resume after departure; harden rate transaction failure paths before clock work.

## What was implemented
Rollback restores original PCM/cache/future references without resampling again.
Failed native close retains the stream, pauses rendering and aborts endpoint
fallback. Stop failure still attempts close; close can be retried explicitly.

## Files changed
`src/cueplayer/playback/audio_engine.py`,
`tests/playback/test_stream_rate_transaction.py`, AI report/handoff pointers.

## Architecture decisions
No DAC clock behavior change. Unresolved native ownership must not be discarded.
Preserve Unicode, single device/routing, multi-version and shared video clock.

## Tests performed
Two new tests failed before fixes: rollback re-entered failed conversion and
close failure opened 20 fake streams. After fixes 70 targeted tests passed in
1.74 seconds (rate transaction, timing, devices, device rate, loop, LTC, video mix).

## Remaining issues
No physical ASIO tests. Existing full-suite/native/UI failures remain. Other
callers of stop/close and full app lifecycle still need later audit; this slice
protects stream startup fallback, not every device-disconnect scenario.

## Suggested next task
Implement a diagnostic-only DAC presentation estimate from recorded callback
blocks and stream time, with timestamp/rate/seek boundary tests. Compare shadow
clock against hardware before changing the public Timeline position contract.
