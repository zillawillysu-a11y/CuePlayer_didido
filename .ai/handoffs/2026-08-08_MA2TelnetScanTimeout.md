# MA2 Telnet Login Test Handoff

## Task objective

Ensure Test Connection does not issue an unsupported MA2 command after Login.

## What was implemented

- Test Connection sends Login only; the previous Echo probe was removed.
- Login still yields 250 ms before later Import/Plugin commands.

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
remaining MA2 command-line error.
