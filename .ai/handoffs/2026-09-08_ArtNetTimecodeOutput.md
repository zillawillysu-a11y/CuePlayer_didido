# Art-Net 4 ArtTimeCode Output

Date: 2026-09-08. Branch: `cursor/technical-audit-0815-028d`.

## Task objective

Add official ArtTimeCode output based on the AudioEngine sample-clock snapshot, plus
settings, diagnostics, tests, and file-LTC TRANS routing. Keep scope output-only.

## What was implemented

- Official 19-byte OpTimeCode encoder and 24/25/29.97 DF/30 fps conversion.
- Dedicated non-GUI, non-audio-callback UDP 6454 sender with directed broadcast and
  unicast, explicit local IPv4 binding, lifecycle handling, and duplicate protection.
- Persisted settings, status/error UI, and independent `ArtTC` quick toggle.
- TRANS routes one decoded file-LTC value to independently enabled MTC and Art-Net TC;
  Art-Net-only translation does not require MIDI.
- PERF metrics, protocol design documentation, tests, and Artistic Licence credit.

## Files changed

Primary files: `src/cueplayer/playback/artnet_timecode.py`,
`src/cueplayer/playback/audio_engine.py`, `src/cueplayer/domain/models.py`,
`src/cueplayer/persistence/project_store.py`, UI/remote/diagnostics modules,
Art-Net/TRANS/persistence/UI tests, `docs/ARTNET_TIMECODE_DESIGN.md`, product/user docs,
report and next task.

## Architecture decisions

- AudioEngine sample position remains the sole clock; Art-Net does not consume MTC.
- UDP never executes in PortAudio callback or GUI QTimer; MTC sender is unchanged.
- TRANS is shared source selection; MTC and Art-Net are independent destinations.
- Both translated outputs share a single LTC decode refresh when both are active.
- Limited broadcast is forbidden; selected-interface directed broadcast is used.
- No input, receive, chase, external control, master/slave, or ArtDmx code exists.

## Tests performed

- Focused Art-Net/TRANS/persistence/UI/Web Remote: **158 passed**.
- Broad safe playback subset: **248 passed**.
- Timecode: **32 passed**; changed UI: **16 passed**.
- Compileall and diff check passed; known unrelated Windows baseline blockers are
  documented in `.ai/REPORT.md`.

## Remaining issues

- Wireshark or DMX-Workshop recognition and external-receiver continuity remain the
  physical acceptance gate.
- Hardware stress must confirm ~30 ArtTimeCode/s, simultaneous ~120 MTC QF/s,
  zero audio underflow/send failure, and zero duplicate sender.

## Suggested next task

Run the physical verification matrix in `.ai/NEXT_TASK.md`, including normal ArtTC
and TRANS ArtTC-only/MTC+ArtTC under Video + Timeline Zoom load. Capture PERF and
receiver evidence before considering any timing change.
