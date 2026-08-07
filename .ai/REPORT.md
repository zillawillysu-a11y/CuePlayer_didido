# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Make an MA2-imported Song View retain the Macro Pool's configured position
instead of placing it over the Sequence Pool.

## What was implemented

- Changed generated MA2 `Widget` attributes to the same order used by MA2's own View export.
- Macro focus flags and its `x` coordinate are now written before `anz_rows`/`anz_cols`; MA2 otherwise ignores the Macro position despite the XML being formally valid.
- Kept the existing fixed MA2 Widget indices and the user's editable layout geometry intact.
- Added a regression assertion against the serialized XML attribute order.

## Files changed

- `src/cueplayer/exporters/ma2/exporter.py`
- `tests/exporters/test_show_patch.py`

## Architecture decisions

- Treat MA2 View XML as a compatibility format rather than a generic XML format: native attribute ordering is part of the import contract.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_show_patch.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-native-widget-attrs`
- Result: **19 passed**.

## Remaining issues

- The user must re-export and import the newly generated View once to verify against MA2 itself.
- Per-song Main/Button export content selection remains pending.
- Telnet remains disabled.
- `startup_error.txt` was not modified.

## Suggested next task

After MA2 verification, add expandable per-song Main/Button export content selection.
