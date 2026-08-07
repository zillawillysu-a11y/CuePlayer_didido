# Next task

**Status:** Queued - awaiting real local Telnet verification after graceful Exit
**Type:** MA2 Telnet validation
**Updated:** 2026-08-08

## Current task

Verify graceful Exit, Import completion, Plugin execution, and scanner output.

## Requirements

- Retest Test Connection and verify MA2 logs Login only after its greeting.
- Leave optional Import Path blank.
- Use Import Plugin & Scan at an empty Plugin Pool, such as 5.
- Verify MA2 logs `Import "CuePlayer_Live_Scan" At Plugin 5`, then `Plugin 5`.
- Confirm all three Telnet status lights become green after scanner output.
- If no frame arrives, copy the new diagnostic status and System Monitor lines.
- Do not touch `startup_error.txt`.
