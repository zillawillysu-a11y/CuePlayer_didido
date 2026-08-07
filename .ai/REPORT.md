# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Fix Scanner Plugin import compatibility after manual MA2 3.9.60 import failed.

## What was implemented

- Changed the Telnet client to issue MA2's required command-line form:
  `Login "<MA2 Show User>" "<password>"`.
- Made Scanner Plugin XML configure its schema from the selected MA2 output
  directory; a 3.9.60 directory now generates 3.9.60 XML rather than 3.9.61.
- Corrected the automatic onPC import path to MA2's virtual plugins path
  `/data/ma/actual/gma2/plugins` instead of a Windows filesystem path.
- Import Plugin & Scan always rewrites the scanner Plugin before importing it.

## Files changed

- `src/cueplayer/exporters/ma2_telnet.py`
- `src/cueplayer/exporters/ma2/exporter.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_ma2_telnet.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `docs/MA2_TELNET_LIVE_SCAN.md`

## Architecture decisions

- The Plugin XML schema must match the selected MA2 library version.
- MA2 Command Import paths use MA2's virtual filesystem paths, not Windows
  filesystem paths.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_ma2_telnet.py tests\\exporters\\test_show_patch.py tests\\persistence\\test_schema.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-scanner-plugin-import`
- Result: **42 passed** using simulated Command/Monitor sockets.

## Remaining issues

- Regenerate the scanner Plugin and retest manual or Telnet import on MA2
  3.9.60, then confirm its System Monitor frame.
- `startup_error.txt` remains untouched.

## Suggested next task

Click Write Scan Plugin to regenerate the matching XML, then use Import Plugin
& Scan at an empty Plugin Pool and confirm all three status lights become green.
