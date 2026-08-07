# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Add a safe Telnet Plugin installation flow and visible connection status to the
MA2 live Pool scanner.

## What was implemented

- Added a persisted Scanner Plugin Pool field (default `9999`) and MA2-visible
  Plugin import path.
- Added **Import Plugin & Scan**. It imports `CuePlayer_Live_Scan` into the
  selected Plugin Pool, executes that exact Pool, and applies safe starts only
  after a valid scanner frame returns.
- Added three status lights: Command Telnet, System Monitor, and Plugin/Scan.
- Kept the existing read-only Test Connection and Scan Current Show actions.
- Added an explicit warning before import because MA2 can overwrite the chosen
  Plugin Pool.

## Files changed

- `src/cueplayer/exporters/ma2_telnet.py`
- `src/cueplayer/domain/models.py`
- `src/cueplayer/persistence/project_store.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_ma2_telnet.py`
- `tests/persistence/test_schema.py`
- `docs/MA2_TELNET_LIVE_SCAN.md`

## Architecture decisions

- Command Telnet performs the explicit MA2 Import and Plugin execution; System
  Monitor remains the read channel for a framed result.
- Plugin Pool occupancy cannot be queried atomically, so CuePlayer requires an
  operator-selected empty ID and confirmation instead of claiming it can safely
  detect or prevent all overwrites.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_ma2_telnet.py tests\\exporters\\test_show_patch.py tests\\persistence\\test_schema.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-telnet-install-status`
- Result: **39 passed** using simulated Command/Monitor sockets.

## Remaining issues

- A real MA2/onPC must verify the installed version accepts the MA2 Plugin
  import path and exposes the scanner frame in System Monitor.
- `startup_error.txt` remains untouched.

## Suggested next task

Run **Write Scan Plugin -> Import Plugin & Scan** against an empty MA2 Plugin
Pool, then confirm all three status lights become green and the safe starts are
correct.
