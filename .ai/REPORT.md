# Audio callback continuity counters reset on new output stream

Date: 2026-09-06. Branch: `technical-audit-0815-028d`. Baseline: `29a0632`. Status: complete.

## Task objective

Reset audio callback continuity diagnostic counters when opening a new output stream, with a narrow playback regression test. LTC Generator Clips Phase 1–4 not touched.

## What was implemented

- Identified that `_cb_count`, `_cb_underflow`, `_cb_status_flags_or`, `_cb_interval_sum`,
  `_cb_interval_count`, `_cb_interval_max`, `_cb_exec_sum`, `_cb_exec_max`, `_cb_deadline_miss`,
  `_cb_miss_play_decode_sum`, `_cb_miss_va_window_sum`, `_cb_miss_play_decode_last`,
  `_cb_miss_va_window_last` in `AudioEngine` are PortAudio-callback continuity counters scoped to
  one output stream's lifetime, but were never reset across stream reopen — they accumulated
  across every `_open_output_stream()` call for the process lifetime.
- Added `AudioEngine._reset_audio_callback_continuity()` in `src/cueplayer/playback/audio_engine.py`
  clearing exactly those counters.
- Called it in `_open_output_stream()` immediately after `stream.start()` succeeds (and after the
  reported-samplerate check), before `return True`. A failed `sd.OutputStream(...)`, a rejected
  samplerate, or a `stream.start()` failure all raise before this line and are handled by the
  existing except block, which never calls the reset — so diagnostics for the previous, still-live
  stream survive a failed reopen attempt untouched.
- `_cb_last_mono` / `_cb_expected_period` were already reset unconditionally at the top of
  `_open_output_stream()` before this change (pre-existing behavior); left untouched to keep the
  fix narrow.
- No changes to playback clock math, sample position semantics, seek, routing, LTC/MTC, exporters,
  or UI.

## Files changed

- `src/cueplayer/playback/audio_engine.py`
- `tests/playback/test_audio_timing_diagnostics.py`
- `.ai/REPORT.md`, `.ai/handoffs/2026-09-06_AudioContinuityReset.md`, `.ai/NEXT_TASK.md`

## Tests performed

- New regression test
  `test_new_stream_resets_continuity_counters_but_failed_open_does_not` in
  `tests/playback/test_audio_timing_diagnostics.py`: accumulates counters via direct callback
  invocation, asserts a failed `_open_output_stream()` (monkeypatched `sd.OutputStream` raising on
  `start()`) leaves counters untouched, then asserts a subsequent successful open resets them to
  zero.
- `tests/playback/test_audio_timing_diagnostics.py` + `tests/playback/test_stream_rate_transaction.py`:
  **16 passed**.
- `tests/playback` (excluding `test_video_sync.py`, which crashes the interpreter with a Windows
  access violation unrelated to this change — pre-existing, reproduces identically on baseline
  `29a0632`): **272 passed, 3 pre-existing failures** (`test_ndi_probe.py::test_ensure_ndi_runtime_search_path_adds_dll_dir`,
  `test_song_use_left_ltc.py::test_file_ltc_right_strips_right_from_music`,
  `test_song_use_left_ltc.py::test_song_use_left_ltc_routes_left_to_ltc_bus`) — reproduced
  identically with the change stashed, confirming they are unrelated to this fix.
- `git diff --check`: passed.

## Remaining issues (pre-existing, not in scope)

- `tests/playback/test_video_sync.py` crashes pytest with a Windows access violation in a
  background thread; unrelated to audio-stream diagnostics.
- `test_ndi_probe.py::test_ensure_ndi_runtime_search_path_adds_dll_dir` and two
  `test_song_use_left_ltc.py` routing assertions fail on this machine independent of this change.
- Carry-over (parked by user): physical loopback 440 Hz + long-capture drift check.

## Suggested next task

Not started; see `.ai/NEXT_TASK.md`.
