# MA2 Telnet Scan Timeout Handoff

## Task objective

Keep the MA2 live scanner connected long enough for its read-only Lua Pool
enumeration and improve no-frame diagnostics.

## What was implemented

- Default scanner timeout is now 15 seconds instead of 3.
- Errors distinguish monitor data without a frame from an entirely empty
  monitor response.

## Files changed

- `src/cueplayer/exporters/ma2_telnet.py`

## Architecture decisions

The scanner is still a bounded synchronous adapter using Command Telnet 30000
to trigger a Plugin and System Monitor 30001 to receive framed output.

## Tests performed

`tests/exporters/test_ma2_telnet.py`: 12 passed.

## Remaining issues

Real MA2 verification is still required. `startup_error.txt` was not touched.

## Suggested next task

Run Import Plugin & Scan with Plugin Pool 5 and report the status message plus
System Monitor output if no frame arrives.
