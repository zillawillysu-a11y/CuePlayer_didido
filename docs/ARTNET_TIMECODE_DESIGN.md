# Art-Net 4 ArtTimeCode Output Design

Date: 2026-09-08

## Protocol authority

Implementation authority is the official Artistic Licence document:

- **Art-Net 4 Protocol Release V1.4, Document Revision 1.4dp, 23/10/2025**
- Official download: <https://art-net.org.uk/downloads/art-net.pdf>
- ArtTimeCode definition: document pages 54-56
- UDP/IP rules and source/destination port: document pages 10-13

The required 19-byte ArtTimeCode UDP payload is:

| Offset | Field | Bytes / value |
|---:|---|---|
| 0 | ID | `41 72 74 2d 4e 65 74 00` (`Art-Net\0`) |
| 8 | OpCode | `00 97` (`OpTimeCode = 0x9700`, low byte first) |
| 10 | ProtVerHi | `00` |
| 11 | ProtVerLo | `0e` (protocol revision 14) |
| 12 | Filler1 | `00` |
| 13 | StreamId | `00` (master stream) |
| 14 | Frames | `0..23/24/29`, depending on Type |
| 15 | Seconds | `0..59` |
| 16 | Minutes | `0..59` |
| 17 | Hours | `0..23` |
| 18 | Type | `0` Film/24, `1` EBU/25, `2` DF/29.97, `3` SMPTE/30 |

Art-Net uses UDP port `0x1936` (6454) as both source and destination. The
ArtTimeCode packet strategy marks unicast and broadcast as application-specific and
states that a single controller will generally broadcast. Art-Net packets must not use
the limited-broadcast address `255.255.255.255`; CuePlayer broadcast mode therefore
uses the selected IPv4 interface's directed-broadcast address.

## Minimal integration points

1. **Pure protocol/network adapter**
   - Add `cueplayer.playback.artnet_timecode` for field encoding, supported rate/type
     mapping, SMPTE/drop-frame conversion, IPv4 interface discovery, UDP socket setup,
     and the dedicated sender lifecycle.
   - The socket is non-blocking. All `bind`/`sendto`/`close` operations happen outside
     the PortAudio callback and outside the GUI timer path.

2. **Playback clock bridge**
   - `AudioEngine` passes the existing immutable published sample-clock snapshot to
     the Art-Net sender through a lock-free callable.
   - Art-Net performs its own per-transport-generation monotonic read guard; it does
     not consume MTC packets, QF state, or MIDI timing.
   - Play/Pause/Seek and song timebase calls notify the independent sender. No audio
     buffer, callback, or MTC cadence change is required.

3. **Settings and persistence**
   - Extend `AudioOutputSettings` because the existing Audio/Midi/Timecode machine
     preference path already owns output-device choices and is mirrored into project
     JSON for backward-compatible round-trips.
   - Persist enable, local IPv4, destination mode, and destination IPv4. The legacy
     fps field remains readable for compatibility, but runtime ArtTimeCode fps/type
     always follows the current Song timebase. Port stays fixed at official 6454.

4. **UI**
   - Add an independent `Art-Net Timecode Output` group to
     `AudioTimecodeDialog`, adjacent to MIDI/LTC output settings.
   - Show fps/type as a read-only `Follow Song FPS` value, not an independent choice.
   - Place TRANS in its own `Timecode Translation` group before MIDI/MTC and Art-Net;
     show the currently enabled translation destinations inline.
   - Populate local-interface choices from active IPv4 interfaces and show their
     directed-broadcast addresses. Broadcast mode fills/validates that address;
     unicast mode accepts one explicit IPv4 receiver address.
   - Display an inline ready/error summary. Runtime socket errors also flow through
     the existing `AudioEngine.apply_audio_settings()` warning path.

5. **Diagnostics**
   - Add an `Art-Net Timecode continuity` PERF report section containing send count,
     calculated sends/second, failures, send duration, scheduler lateness, and live
     duplicate-worker evidence.

6. **Tests**
   - Exact 19-byte official-field vectors and all four Type values.
   - 29.97 drop-frame minute and ten-minute boundaries.
   - Mock-socket bind/directed-broadcast/unicast behavior.
   - Play/Pause/Seek/idempotent lifecycle and direct sample-snapshot following.
   - Simultaneous MTC and ArtTimeCode output with independent expected cadences.
   - Settings/project/global-prefs round-trip and UI validation/state tests.

## Explicit non-goals

- Art-Net Timecode input.
- ArtDmx, ArtPoll, discovery, or OEM identity packets.
- Deriving ArtTimeCode from MTC messages.
- Any second playback clock, GUI `QTimer` sender, PortAudio callback networking,
  audio-buffer change, or MTC sender behavior change.

## Product credit

Before public distribution documentation is finalized, include the specification's
required credit: **Art-Net™ Designed by and Copyright Artistic Licence**. This feature
does not implement ArtPoll/ArtPollReply and therefore does not introduce OEM fields;
any broader Art-Net product conformance/OEM registration work remains separate.
