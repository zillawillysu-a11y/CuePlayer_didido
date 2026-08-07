# MA2 Telnet login protocol fix

## Task objective

Fix the immediate MA2 Command Telnet disconnect observed during live testing.

## What was implemented

- Replaced raw username/password socket writes with MA2's required
  `Login "user" "password"` command.
- Rejects missing MA2 show user values before sending commands.
- Clarified the UI label and live-scan documentation.

## Files changed

- `src/cueplayer/exporters/ma2_telnet.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_ma2_telnet.py`
- `docs/MA2_TELNET_LIVE_SCAN.md`

## Architecture decisions

- The client follows the documented MA2 command-line authentication model;
  it does not implement a generic Telnet username/password prompt protocol.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_ma2_telnet.py tests\\exporters\\test_show_patch.py tests\\persistence\\test_schema.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-telnet-login-fix`
- Result: **40 passed**.

## Remaining issues

- Retest with a real MA2 Show User and password. The MA2 System Monitor scan
  response still needs real-console confirmation.
- `startup_error.txt` remains untouched.

## Suggested next task

Run Test Connection with real MA2 show credentials, then test
**Import Plugin & Scan** in an empty Plugin Pool.
