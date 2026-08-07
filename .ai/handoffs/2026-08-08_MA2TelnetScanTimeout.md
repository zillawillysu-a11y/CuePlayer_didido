# MA2 Telnet Graceful Exit Handoff

## Task objective

Close MA2 Command Telnet using its documented `Exit` keyword.

## What was implemented

- Test, Import, and Scan send `Exit` before their Command socket closes.
- Import feedback remains open for up to 1.5 seconds before Exit.

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

Run Import Plugin & Scan with Plugin Pool 6 and verify MA2 logs `Exit`, the
Plugin body is present, and no new `Send`/`Recv` exception appears.
