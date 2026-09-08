# Art-Net 4 ArtTimeCode Output

Date: 2026-09-08. Branch: `cursor/technical-audit-0815-028d`.

## Task objective

Implement production Art-Net 4 ArtTimeCode output, derived directly from the
AudioEngine sample-clock snapshot, without changing the stable MTC/audio paths. Add
independent settings/UI, diagnostics, tests, and file-LTC TRANS routing to independently
enabled MTC and Art-Net outputs. Output only; no receive/chase/ArtDmx scope.

## What was implemented

- Researched the official Artistic Licence Art-Net 4 Protocol Release V1.4,
  Document Revision 1.4dp (23/10/2025), and documented the exact 19-byte
  ArtTimeCode layout, little-endian OpTimeCode, protocol version, Type values,
  UDP 6454 requirements, and directed-broadcast/unicast behavior.
- Added a dedicated, idempotent ArtTimeCode sender thread. It reads the same immutable
  sample-clock snapshot as the stable timecode system, performs non-blocking UDP sends,
  and never runs network code in the PortAudio callback or GUI QTimer.
- Added 24, 25, 29.97 DF, and 30 fps conversion and packet encoding, including legal
  29.97 drop-frame labels and 24-hour wrapping.
- Added Play/Pause/Stop/Seek lifecycle integration, explicit local IPv4 interface,
  directed broadcast or explicit unicast destination, sender error/status reporting,
  and duplicate-live-sender protection.
- Added persisted Art-Net settings and an Audio / Midi / Timecode dialog section.
- Added an `ArtTC` monitor quick toggle, independent of MIDI, beside the existing
  TRANS / Note / MTC / LTC controls with narrow-layout wrapping.
- Generalized TRANS: file LTC is decoded once per refresh and the identical decoded
  value is independently re-anchored into enabled MTC and/or Art-Net TC. Art-Net-only
  translation no longer requires MIDI or a MIDI port.
- Added PERF evidence for send count/rate/failures, send duration, wakeup lateness,
  and duplicate live sender count, plus the required Artistic Licence product credit.

## Files changed

- Protocol/sender: `src/cueplayer/playback/artnet_timecode.py`
- Clock/lifecycle/TRANS integration: `src/cueplayer/playback/audio_engine.py`
- Domain/persistence: `src/cueplayer/domain/models.py`,
  `src/cueplayer/persistence/project_store.py`
- UI/remote: `src/cueplayer/ui/audio_timecode_dialog.py`,
  `src/cueplayer/ui/output_quick_toggles.py`, `src/cueplayer/ui/cue_monitor_panel.py`,
  `src/cueplayer/ui/main_window.py`, `src/cueplayer/web_remote/bridge.py`,
  `src/cueplayer/web_remote/state.py`
- Diagnostics/packaging: `src/cueplayer/diagnostics/perf.py`, `packaging/cueplayer.spec`
- Tests: Art-Net playback tests plus TRANS, persistence, UI, and quick-toggle regressions
- Docs: `docs/ARTNET_TIMECODE_DESIGN.md`, product/user docs, README, workflow records

## Architecture decisions

- AudioEngine playback sample position remains the only playback clock. Art-Net reads
  the same published snapshot directly and is never derived from MTC packets.
- Art-Net owns one independent sender thread and UDP socket; MTC cadence and sender
  implementation are unchanged. The sender binds and sends on official UDP port 6454.
- File-LTC decoding remains outside the audio callback. When both MTC and Art-Net
  translation are enabled, the existing MTC worker owns the periodic decode and shares
  its result; in Art-Net-only mode, the Art-Net worker requests that same decode path.
- TRANS is shared source selection, while MTC and Art-Net Enable remain independent
  destinations. Note/MTC are MIDI-dependent; TRANS/ArtTC are not.
- Limited broadcast `255.255.255.255` is rejected; broadcast uses the selected
  interface's directed broadcast. Explicit unicast is supported.
- No input, receive, chase, incoming control, master/slave logic, or ArtDmx was added.

## Tests performed

- Art-Net/TRANS/persistence/UI/Web Remote focused regression batch: **158 passed**.
- Broad playback batch excluding known Windows environment/native-baseline files:
  **248 passed**.
- Timecode suite: **32 passed**; changed UI suite: **16 passed**.
- `python -m compileall -q src`: passed.
- `git diff --check`: passed (only CRLF conversion notices).
- Full playback collection is not green on this workstation for unrelated baseline
  reasons: installed NDI Runtime breaks `test_ndi_probe.py`'s isolated-path assumption;
  cumulative `test_video_sync.py` can terminate with a native access violation;
  `test_song_use_left_ltc.py` observes real-machine persisted device/routing state.

## Remaining issues

- Automated tests validate official fields/vectors, cadence simulation, lifecycle,
  simultaneous ~30 ArtTimeCode/s + ~120 MTC QF/s, TRANS routing, and duplicate prevention.
- Physical verification is still required with Wireshark or DMX-Workshop and an
  external Art-Net receiver.
- Repeat Video + Timeline Zoom stress with both outputs and record ~30 ArtTimeCode/s,
  ~120 QF/s, zero send failures, duplicate sender 0, and audio underflow 0.

## Suggested next task

Build this commit on Windows, select the correct Art-Net NIC/directed broadcast, and
perform Wireshark or DMX-Workshop plus external-receiver hardware verification. Test
normal Song TC and both TRANS matrices (ArtTC-only and MTC+ArtTC) through
Play/Pause/Stop/Seek under Video + Timeline Zoom stress; capture PERF and receiver
evidence. Do not modify MTC/audio architecture unless that evidence proves a regression.
