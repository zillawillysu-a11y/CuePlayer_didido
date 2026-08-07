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
- Regenerate the Scanner Plugin for MA2 3.9.60, import it at an empty numeric
  Plugin Pool, then run Scan Current Show and inspect the System Monitor frame.
- Confirm all three Telnet status lights become green after a completed scan.
- Verify all five computed starts (Sequence, Effect, Timecode, Song Macro,
  View) match actual occupied Pools.
- Confirm errors/unsupported versions leave Console Setup unchanged.
- Do not touch `startup_error.txt`.
