# MA2 Telnet install and status

## Task objective

Allow CuePlayer to install the live scanner Plugin through Command Telnet and
show the stage of Telnet readiness in the Export Registry.

## What was implemented

- Added persisted Scanner Plugin Pool (default `9999`) and MA2-visible import
  path fields.
- Added **Import Plugin & Scan**. It sends MA2's `Import` command to the
  chosen Plugin Pool, then executes that Plugin Pool and synchronizes the
  Registry only when a valid scanner frame is returned.
- Added three status lights for Command Telnet, System Monitor, and
  Plugin/Scan.
- Added a required overwrite warning because MA2 Import can overwrite an
  occupied Plugin Pool.

## Files changed

- `src/cueplayer/exporters/ma2_telnet.py`
- `src/cueplayer/domain/models.py`
- `src/cueplayer/persistence/project_store.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_ma2_telnet.py`
- `tests/persistence/test_schema.py`
- `docs/MA2_TELNET_LIVE_SCAN.md`

## Architecture decisions

- The client remains synchronous and isolated from exporter XML generation.
- The UI cannot safely determine Plugin Pool occupancy remotely, so the
  operator must choose an empty Plugin Pool and explicitly confirm install.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_ma2_telnet.py tests\\exporters\\test_show_patch.py tests\\persistence\\test_schema.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-telnet-install-status`
- Result: **39 passed**.

## Remaining issues

- Real MA2/onPC must verify its exact import path syntax and Plugin/System
  Monitor behavior.
- `startup_error.txt` is untouched.

## Suggested next task

Run **Write Scan Plugin -> Import Plugin & Scan** against an empty MA2 Plugin
Pool, then confirm all three status lights turn green and the safe starts are
correct.
