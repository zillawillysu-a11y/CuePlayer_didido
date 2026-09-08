# Video waveform batch continuity

Date: 2026-09-05. Branch: `cursor/technical-audit-0815-028d`.

## Task objective
Preserve decoded samples/PTS across video-waveform batch and seek boundaries.

## What was implemented
Carry partial decoded frames into the next batch, trim real samples at seek,
recreate flushed resampler, preserve true PTS gaps rather than compressing time.
Use integer frame accumulation and bounded pending tail. Artifact version 7
invalidates potentially damaged v6 waveforms lazily; no source media mutation.

## Files changed
`src/cueplayer/media/video_waveform_artifact.py`,
`tests/media/test_waveform_decoder_continuity.py`, AI report/handoff pointers.

## Architecture decisions
Only waveform analysis decoder changes; playback audio/video decode untouched.
Reuse source artifact architecture, worker/process policy and Unicode paths.
Old cached artifacts must rebuild because they contain no PCM to recover gaps.

## Tests performed
Four real-decoder cases failed before fixes. After fixes: 32 media tests passed
with clean exit in 2.91s. Float WAV at 44.1/48/96k reconstructs all 25 seconds
sample-for-sample across 8-second batches; seek/reopen and synthetic PTS gap tested.
Expanded media/UI run printed 46 passed in 2.64s but hung during process exit;
the identified test process was terminated. Do not describe it as a clean pass.

## Remaining issues
Need AAC/MP3 embedded-stream variants and real project workload. Native/UI test
lifecycle remains unresolved. ASIO hardware clarification pending, no physical
DAC/pitch claim. Stereo phase cancellation, long PCM RAM, short loop and MTC
issues remain separate.

## Suggested next task
Fix multi-wrap audio callback loop bookkeeping and all routed source chunks,
using sample-exact tests. Keep MTC scheduling and clock changes separate.
