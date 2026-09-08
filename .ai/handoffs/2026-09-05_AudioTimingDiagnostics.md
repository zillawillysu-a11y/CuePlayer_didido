# Phase 0 diagnostics slice

Date: 2026-09-05. Branch: `cursor/technical-audit-0815-028d`.

## Task objective

User authorized commit/push and automatic continuation until hardware input is
needed. Add bounded timing observations and improve test isolation first.

## What was implemented

Opt-in 512-row numeric callback ring, source/processing/callback/reported stream
rates, DAC/current timestamps, seek/open generations and render-state reasons.
Correct diagnostic underflow bit and variable-block interval accounting. No
playback clock, routing, resampling or transport behavior changes in this slice.
Tests retain Qt application/engine/video workers and fake native audio streams.
Removed stale waveform API dependencies by testing source artifacts. Negative
video pre-roll expectation now matches intentional commit 068cb74.

## Files changed

`src/cueplayer/diagnostics/audio_timing.py`, `playback/audio_engine.py`,
`tests/conftest.py`, timing/device/domain/video waveform/video sync tests,
`docs/AUDIO_TIMING_DIAGNOSTICS.md` and AI handoff pointers.

## Architecture decisions

Trace is disabled by default, bounded and never a clock. No callback I/O/new
locks. Source ready ranges explicitly unknown. No claims of zero probe overhead
or hardware-verified stream rates. Existing product constraints remain intact.

## Tests performed

511 passed: core domain/persistence/export/routing/timecode/application/ports/
repository/core/Unicode plus timing diagnostics, video waveform and device tests.
Focused group including video-sync: 146 passed, 1 failed (near-zero duplicate
frame test emits none). Full-suite attempts still hit native/GUI failures,
including cue-list stack overflow and combined-run video native failure. Isolated
video cleanup improves one run but does not prove native lifecycle fully fixed.
Tracing on/off produces identical output PCM and frame position in regression
tests. Trace capacity/status/variable-block/generation/error observations tested.

## Remaining issues

Full-suite baseline is not green. ASIO pitch/presentation accuracy still untested
on hardware. Production teardown, UI failures and full ready-range contract are
not fixed here. See technical audit for wider outstanding issues.

## Suggested next task

Phase 1a: 小範圍修正 stream 開啟備援取樣率的狀態一致性，加入同步 start callback 與失敗回復測試；完成後 Commit/Push，實機 gate 前不宣稱 ASIO 根因已解決。
