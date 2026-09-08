# MA2 Telnet login prompt wait

## Task objective

Prevent CuePlayer from writing MA2 commands while MA2 is still sending its
initial ANSI login screen.

## What was implemented

- Command Telnet now drains initial output until `Please login !` before it
  writes the MA2 Login command.
- System Monitor uses a short initial drain without waiting for a login prompt.
- Added a delayed-banner regression test.

## Files changed

- `src/cueplayer/exporters/ma2_telnet.py`
- `tests/exporters/test_ma2_telnet.py`
- `docs/MA2_TELNET_LIVE_SCAN.md`

## Architecture decisions

- MA2's ANSI login screen is a readiness handshake for the Command adapter.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_ma2_telnet.py tests\\exporters\\test_show_patch.py tests\\persistence\\test_schema.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-telnet-login-prompt`
- Result: **44 passed**.

## Remaining issues

- Real MA2/onPC must confirm the delayed greeting no longer causes Send errors.
- `startup_error.txt` remains untouched.

## Suggested next task

Retest Test Connection, then Import Plugin & Scan at Plugin Pool 5 with the
optional Import Path blank.
