# MA2 scanner Plugin import compatibility

## Task objective

Fix manual and Telnet import failures for the Scanner Plugin on MA2 3.9.60.

## What was implemented

- Scanner Plugin XML now derives its schema version from the selected MA2
  output path.
- Local MA2 onPC imports now use the MA2 virtual plugins directory instead of
  a Windows filesystem path.
- Import Plugin & Scan regenerates the scanner files before it imports them.

## Files changed

- `src/cueplayer/exporters/ma2/exporter.py`
- `src/cueplayer/exporters/ma2_telnet.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_show_patch.py`
- `docs/MA2_TELNET_LIVE_SCAN.md`

## Architecture decisions

- Scanner Plugin XML follows the same version-from-output-path schema logic as
  existing MA2 export files.
- MA2 virtual file paths are part of the Telnet adapter boundary.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_ma2_telnet.py tests\\exporters\\test_show_patch.py tests\\persistence\\test_schema.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-scanner-plugin-import`
- Result: **42 passed**.

## Remaining issues

- Real MA2 3.9.60 must import the regenerated scanner Plugin and return a
  System Monitor scanner frame.
- `startup_error.txt` remains untouched.

## Suggested next task

Click Write Scan Plugin again, then Import Plugin & Scan at an empty Plugin
Pool and confirm the scanner is visible in MA2's Plugin Pool.
