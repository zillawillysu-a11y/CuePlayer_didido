# MA2 Telnet Import Completion Handoff

## Task objective

Ensure MA2 completes the Import command before CuePlayer closes Command Telnet.

## What was implemented

- Import feedback is drained for up to 1.5 seconds before socket close.
- Test Connection sends Login only; Login still yields 250 ms before later
  Import/Plugin commands.

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

Run Import Plugin & Scan with Plugin Pool 6 and report whether the Plugin body
is present and whether MA2 logs another `Send` exception.
