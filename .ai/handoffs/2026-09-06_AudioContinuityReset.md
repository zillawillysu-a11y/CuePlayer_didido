# Handoff: Audio callback continuity counters reset on new output stream

Date: 2026-09-06. Branch: `technical-audit-0815-028d`. Baseline: `29a0632`.

## What changed

`AudioEngine` PortAudio callback continuity counters (underflow/deadline-miss/interval/exec stats
in `src/cueplayer/playback/audio_engine.py`) previously accumulated for the process lifetime across
every output-stream reopen, because nothing reset them. Added
`AudioEngine._reset_audio_callback_continuity()` and call it in `_open_output_stream()` right after
`stream.start()` succeeds. A failed stream open (bad samplerate, `PortAudioError` on construct or
start) never reaches that call, so the previous stream's diagnostics survive a failed reopen.

## Why this scope

`.ai/NEXT_TASK.md` asked for a narrow diagnostic fix: identify stream-lifetime counters, reset them
only on successful reopen, add a regression test. No playback-affecting code (clock math, position,
seek, routing, LTC/MTC, exporters, UI) was touched.

## Test evidence

- New test: `tests/playback/test_audio_timing_diagnostics.py::test_new_stream_resets_continuity_counters_but_failed_open_does_not`.
- `tests/playback/test_audio_timing_diagnostics.py` + `tests/playback/test_stream_rate_transaction.py`: 16 passed.
- `tests/playback` (excluding `test_video_sync.py`, which crashes the interpreter with an unrelated
  Windows access violation): 272 passed, 3 pre-existing failures unrelated to this change (verified
  identical on `29a0632` via `git stash`).
- `git diff --check`: passed.

## Next task

See `.ai/NEXT_TASK.md`.
