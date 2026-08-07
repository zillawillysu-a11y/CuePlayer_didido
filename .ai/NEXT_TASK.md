# Next task

**Status:** Queued — awaiting real MA2/onPC Telnet verification
**Type:** MA2 Telnet validation
**Updated:** 2026-08-08

## Current task

Test the CuePlayer Live Scan Plugin through real MA2 Command Telnet and
System Monitor.

## Requirements

- Confirm Command login and System Monitor port access on a real MA2/onPC.
- Write/import the Plugin, then run Scan Current Show.
- Verify all five computed starts (Sequence, Effect, Timecode, Song Macro,
  View) match actual occupied Pools.
- Confirm errors/unsupported versions leave Console Setup unchanged.
- Do not touch `startup_error.txt`.
