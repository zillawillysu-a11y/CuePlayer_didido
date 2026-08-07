# MA2 Telnet negotiation fix

## Task objective

Make CuePlayer behave as a Telnet client rather than a raw TCP command sender
when connecting to MA2 port 30000.

## What was implemented

- Added Telnet IAC option negotiation and safe replies before sending MA2
  commands.
- Retained MA2 command-line Login syntax and added short Test Connection
  feedback display.
- Added a regression test for the Telnet option response.

## Files changed

- `src/cueplayer/exporters/ma2_telnet.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_ma2_telnet.py`
- `docs/MA2_TELNET_LIVE_SCAN.md`

## Architecture decisions

- CuePlayer declines optional Telnet terminal features and needs no terminal
  emulation, only a standards-compliant negotiation response.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_ma2_telnet.py tests\\exporters\\test_show_patch.py tests\\persistence\\test_schema.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-telnet-negotiate`
- Result: **41 passed**.

## Remaining issues

- Real MA2/onPC validation remains required for the command response,
  Plugin import path, and System Monitor scanner frame.
- `startup_error.txt` remains untouched.

## Suggested next task

Retest Command Telnet with a valid MA2 Show User/password, then run
**Import Plugin & Scan** against an empty Plugin Pool.
