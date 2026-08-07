# Next task

**Status:** Queued - awaiting real local Telnet Import verification
**Type:** MA2 Telnet validation
**Updated:** 2026-08-08

## Current task

Verify the local MA2 Telnet Import command and subsequent scanner execution.

## Requirements

- Leave optional Import Path blank.
- Use Import Plugin & Scan at an empty Plugin Pool, such as 5.
- Verify MA2 logs `Import "CuePlayer_Live_Scan" At Plugin 5`, then `Plugin 5`.
- Confirm all three Telnet status lights become green after scanner output.
- Do not touch `startup_error.txt`.
