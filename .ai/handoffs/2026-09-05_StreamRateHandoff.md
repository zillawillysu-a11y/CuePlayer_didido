# Stream rate transaction — departure handoff

Date: 2026-09-05. Branch: `cursor/technical-audit-0815-028d`.
User asked to stop and hand off before disconnecting the network.

## Task objective

Continue the technical audit in small committed phases. Phase 0 diagnostics was
committed/pushed as `e6fe20c`; current slice addresses H02 fallback rate state.

## What was implemented

- Prepare changed-rate music PCM, mixer rate, LTC invalidation/cursor and sample
  position before stream.start(), which can invoke callbacks synchronously.
- Preserve logical seconds when changing rate; token records the final rate.
- Reject a stream-reported rate different from the callback's requested rate.
- Close a stream whose start fails and restore prior rate/position/play state.
- Keep ordinary same-rate deferred prewarm behavior; no Timeline clock change.
- Record last failed stream attempt in diagnostics without falsely warning about
  an ordinary low-latency rejection followed by a successful normal open.
- Update stale video-audio test cache injection to current window/snapshot API,
  isolate synthetic device channel probes and explicitly select generated LTC
  for the music-volume/LTC test.

## Files changed

- `src/cueplayer/playback/audio_engine.py`
- `tests/playback/test_stream_rate_transaction.py`
- `tests/playback/test_audio_engine_source_ltc.py`
- `tests/playback/test_audio_engine_video_mix.py`
- `.ai/REPORT.md`, `.ai/NEXT_TASK.md`, this handoff

## Architecture decisions

No rewrite, no presentation-clock fix yet, no source readiness/streaming change.
AudioEngine remains clock owner. Unicode, multi-version audio, single output
device/free routing, shared video and MA export behavior remain requirements.
Rate fallback still uses the existing synchronous resample wait; do not claim
long-file UI latency is fixed. User's departure request pauses auto-continuation.

## Tests performed

New regression tests failed against pre-fix code: 5 failed / 1 passed. After
fixes, 68 passed in 1.77 seconds across stream-rate transaction, diagnostics,
device negotiation, device-rate playback, A-B loop, source LTC and video mix.
Cases include 44.1/48/96k source/target combinations, immediate start callback,
start failure cleanup, stream-reported mismatch rejection and final fallback token.
`git diff --check` run before handoff commit.

## Remaining issues

- This is a verified narrow slice, not completion of Phase 1 or release approval.
- No ASIO/Focusrite loopback or physical waveform/pitch validation. H02 being
  fixed does not prove it caused the user's intermittent vocal pitch symptom.
- Review conversion failure/rollback and close-failure paths further before
  broadening rate transaction behavior. Full-file fallback conversion can block UI.
- Phase 0: 511 focused/core tests passed; full suite remains non-green, with
  combined-run native video failures, cue-list UI stack overflow, and an isolated
  near-zero duplicate-frame test failure. Never claim lifecycle fully repaired.
- H01 DAC presentation clock, H03 ready ranges, short-loop defect, fractional
  FPS, bounded caches, atomic save, NDI teardown and Theatre mode remain open.
- Keep `CUEPLAYER_TECHNICAL_AUDIT.md` as historical d9663ec audit; do not interpret
  its line numbers or baseline probe expected defects as post-fix guarantees.

## Suggested next task

Resume with a focused review/test of the stream-rate transaction failure and
rollback paths; then tackle H01 DAC presentation clock with fake timestamps and
seek/pause/loop generation tests. Request hardware loopback only when necessary
to establish actual ASIO/presentation accuracy. Read this handoff, the technical
audit and `docs/AUDIO_TIMING_DIAGNOSTICS.md` first. Commit/push small slices.
