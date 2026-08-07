# MA2 Telnet control-packet filter

## Task objective

Remove Telnet negotiation bytes from CuePlayer's visible MA2 feedback.

## What was implemented

- Added a shared Telnet decoder that responds to option commands and returns
  only displayable text.
- Applied it to initial negotiation, Test Connection feedback, and System
  Monitor scanner data.
- Added a regression test that proves binary Telnet bytes do not reach the
  UI feedback text.

## Files changed

- `src/cueplayer/exporters/ma2_telnet.py`
- `tests/exporters/test_ma2_telnet.py`
- `docs/MA2_TELNET_LIVE_SCAN.md`

## Architecture decisions

- Telnet handling remains contained in the MA2 transport adapter; UI receives
  cleaned text only.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_ma2_telnet.py tests\\exporters\\test_show_patch.py tests\\persistence\\test_schema.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-telnet-control-filter`
- Result: **42 passed**.

## Remaining issues

- Real MA2/onPC must still validate that login succeeds and the scanner Plugin
  returns its System Monitor frame.
- `startup_error.txt` remains untouched.

## Suggested next task

Retest Test Connection and capture the cleaned MA2 status text, then test
**Import Plugin & Scan** using an empty Plugin Pool.
