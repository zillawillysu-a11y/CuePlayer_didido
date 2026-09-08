# MA2 Telnet Plugin Pool execution

## Task objective

Fix MA2 scanner execution after MA2 rejected `Plugin "CuePlayer Live Scan"`.

## What was implemented

- Scan Current Show now executes the configured numeric Plugin Pool.
- The Telnet scanner requires a Plugin Pool ID for every scan.
- Added regression tests for both the transport command and UI forwarding.

## Files changed

- `src/cueplayer/exporters/ma2_telnet.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_ma2_telnet.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `docs/MA2_TELNET_LIVE_SCAN.md`

## Architecture decisions

- Plugin display names are labels; MA2 execution uses an explicit Plugin Pool
  ID persisted in MA export settings.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_ma2_telnet.py tests\\exporters\\test_show_patch.py tests\\persistence\\test_schema.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-telnet-plugin-pool`
- Result: **42 passed**.

## Remaining issues

- Real MA2/onPC must confirm the scanner Plugin is imported into the selected
  Pool and that System Monitor returns its frame.
- `startup_error.txt` remains untouched.

## Suggested next task

Open MA2's Plugin Pool, verify the scanner at the configured number, then run
CuePlayer's **Scan Current Show** and inspect the status lights.
