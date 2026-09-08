# MA2 Telnet local Import command

## Task objective

Match CuePlayer's local Telnet Import command with the command verified by the
operator in MA2's own command line.

## What was implemented

- Local imports now send `Import "CuePlayer_Live_Scan" At Plugin N` with no
  automatic `/path` or `/nc` suffix.
- The import path is optional and only used for remote-console deployments.
- Added an exact-command regression test for local Plugin Pool 5.

## Files changed

- `src/cueplayer/exporters/ma2_telnet.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_ma2_telnet.py`
- `docs/MA2_TELNET_LIVE_SCAN.md`

## Architecture decisions

- Real MA2 command-line behavior is the source of truth for the local onPC
  adapter; optional path overrides remain available for remote consoles.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_ma2_telnet.py tests\\exporters\\test_show_patch.py tests\\persistence\\test_schema.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-telnet-local-import`
- Result: **43 passed**.

## Remaining issues

- A real local Telnet Import needs confirmation in MA2 System Monitor, followed
  by scanner Plugin execution and a valid frame.
- `startup_error.txt` remains untouched.

## Suggested next task

Leave Import Path blank, click Import Plugin & Scan at Plugin Pool 5, and
verify MA2 logs the minimal Import command followed by Plugin 5.
