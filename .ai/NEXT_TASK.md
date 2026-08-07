# Next task

**Status:** Queued - awaiting real MA2/onPC Telnet install-and-scan verification
**Type:** MA2 Telnet validation
**Updated:** 2026-08-08

## Current task

Test CuePlayer Live Scan Plugin installation and the full scanner round trip
through real MA2 Command Telnet and System Monitor.

## Requirements

- Confirm Command login and System Monitor port access on a real MA2/onPC.
- Verify Write Scan Plugin -> Import Plugin & Scan using an empty Plugin Pool
  and an MA2-visible Plugin import path.
- Confirm all three Telnet status lights become green after a completed scan.
- Verify all five computed starts (Sequence, Effect, Timecode, Song Macro,
  View) match actual occupied Pools.
- Confirm errors/unsupported versions leave Console Setup unchanged.
- Do not touch `startup_error.txt`.
