# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Run the MA2 scanner by configured Plugin Pool number after MA2 rejected a
Plugin display-name command.

## What was implemented

- Changed the Telnet client to issue MA2's required command-line form:
  `Login "<MA2 Show User>" "<password>"`.
- Changed **Scan Current Show** to execute `Plugin <configured pool>`.
- Made the transport require a numeric Plugin Pool for every scan, preventing
  accidental regressions to the unsupported display-name command.
- Added UI coverage for forwarding the configured Plugin Pool to the scanner.

## Files changed

- `src/cueplayer/exporters/ma2_telnet.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_ma2_telnet.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `docs/MA2_TELNET_LIVE_SCAN.md`

## Architecture decisions

- MA2 Plugin execution is addressed by Pool number; the Plugin name remains a
  label only.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_ma2_telnet.py tests\\exporters\\test_show_patch.py tests\\persistence\\test_schema.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-telnet-plugin-pool`
- Result: **42 passed** using simulated Command/Monitor sockets.

## Remaining issues

- Real MA2/onPC still needs a scan test through the installed numeric Plugin
  Pool and System Monitor frame.
- `startup_error.txt` remains untouched.

## Suggested next task

Verify the scanner is present in the configured Plugin Pool, then run
**Scan Current Show** and confirm all three status lights become green.
