# Next task

**Hardware-verify Art-Net 4 ArtTimeCode output on Windows.**

Build the current `cursor/technical-audit-0815-028d` commit. Select the physical
Art-Net interface and directed broadcast (or explicit unicast receiver), then verify
packets with Wireshark or DMX-Workshop and a real external receiver.

Required matrix:

- Normal ArtTC at 24, 25, 29.97 DF, and 30 fps through Play/Pause/Stop/Seek.
- At 30 fps, approximately 30 valid ArtTimeCode packets/s.
- MTC + ArtTC: approximately 120 MTC QF/s and 30 ArtTimeCode/s.
- File LTC + TRANS: ArtTC-only receives decoded LTC; MTC+ArtTC both receive the same
  decoded LTC labels.
- Video + repeated Timeline Zoom stress: audio underflow 0, Art-Net send failures 0,
  and `artnet_tc.duplicate_live_sender_count` 0.

Capture PERF, packet identification, receiver behavior, and errors. Do not start
Art-Net input/chase/ArtDmx or change the stable MTC sender, audio buffer, PortAudio
callback, or GUI timer architecture unless hardware evidence proves a regression.
