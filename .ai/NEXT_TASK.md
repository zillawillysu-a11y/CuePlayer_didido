# Next task

**Status:** Queued - awaiting real MA2/onPC Telnet login and install verification
**Type:** MA2 Telnet validation
**Updated:** 2026-08-08

## Current task

Retest CuePlayer Live Scan with a real MA2 Show User/password, then verify
Plugin installation and the full scanner round trip.

## Requirements

- Enter an existing, case-sensitive MA2 Show User/password and confirm the
  Test Connection shows cleaned readable MA2 feedback after Telnet negotiation.
- Verify Write Scan Plugin -> Import Plugin & Scan using an empty Plugin Pool
  and an MA2-visible Plugin import path.
- Confirm all three Telnet status lights become green after a completed scan.
- Verify all five computed starts (Sequence, Effect, Timecode, Song Macro,
  View) match actual occupied Pools.
- Confirm errors/unsupported versions leave Console Setup unchanged.
- Do not touch `startup_error.txt`.
