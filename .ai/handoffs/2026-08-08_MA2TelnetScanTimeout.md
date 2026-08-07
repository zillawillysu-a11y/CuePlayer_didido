# MA2 Telnet Login Pacing Handoff

## Task objective

Prevent MA2 Command Telnet from closing when the next command follows Login too
quickly.

## What was implemented

- Login now yields the MA2 command line for 250 ms before the next command.
- Scanner timeout remains 15 seconds and errors distinguish monitor data versus
  an empty monitor response.

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

Run Test Connection and Import Plugin & Scan with Plugin Pool 5; report any
remaining `Send` exception.
