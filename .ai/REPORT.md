# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Wait for MA2's actual Command Telnet login prompt before writing Login or
Import commands.

## What was implemented

- Added Command Telnet initial-screen draining until MA2 emits `Please login !`.
- System Monitor has a short non-blocking initial drain and does not wait for a
  Command login prompt.
- Added a regression test with the delayed ANSI banner and login prompt.

## Files changed

- `src/cueplayer/exporters/ma2_telnet.py`
- `tests/exporters/test_ma2_telnet.py`
- `docs/MA2_TELNET_LIVE_SCAN.md`

## Architecture decisions

- The Command adapter must treat MA2's ANSI login screen as protocol readiness,
  not as generic text that can be ignored after the first socket read.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_ma2_telnet.py tests\\exporters\\test_show_patch.py tests\\persistence\\test_schema.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-telnet-login-prompt`
- Result: **44 passed**.

## Remaining issues

- Real MA2 must confirm Test Connection now logs Login after the greeting,
  then Telnet Import, Plugin 5 execution, and scanner frame.
- `startup_error.txt` remains untouched.

## Suggested next task

Retest Test Connection, then leave Import Path blank and click Import Plugin &
Scan at Plugin Pool 5. Verify MA2 logs Login, Import, then Plugin 5.
