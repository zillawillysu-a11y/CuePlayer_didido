# MA3 Effects and Macro ViewWidget mappings

**Date:** 2026-08-09
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Complete the confirmed grandMA3 ViewWidget mappings for Effects and Macros
using Willy's real grandMA3 2.3.2 View exports, without guessing unsupported
MA3 XML.

## What was implemented

- Added the real `WindowMacroPool` / `MacroPoolSettings` shape.
- Added mode-aware Effects mappings: fixed Effects use Template EFX
  (`PresetPoolType=22`), while per-song Effects use Song EFX
  (`PresetPoolType=24`). Both use the reference `PresetAllPoolSettings`.
- Corrected MA3 pool-range handling after the new reference proved that
  `WindowScrollPositions.ScrollV` is the first visible pool number minus one.
  Fixed pools use `start`; per-song pools use
  `start + song_index * stride`.
- Unsupported View Layout pool types continue to be skipped silently.

## Files changed

- `src/cueplayer/exporters/ma3/exporter.py`
- `tests/exporters/test_ma3_song_workflow.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-09_MA3EffectMacroViewWidgets.md`
- `.ai/NEXT_TASK.md`

## Architecture decisions

- Kept the shared MA2/MA3 View Layout data model unchanged.
- Selected Effects shapes by `type:mode` because the real MA3 exports prove
  fixed Template EFX and per-song Song EFX are distinct PresetAll pools.
- Pool scrolling is derived only from observed real onPC XML examples:
  1409 -> 1408, 51 -> 50, 3161 -> 3160, and 1 -> 0.
- MA2 export behavior and all unconfirmed MA3 pool shapes remain untouched.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/exporters/test_ma3_song_workflow.py -q`
  - 16 passed.
- `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/exporters tests/ui/test_show_patch_ma2_discovery.py -q`
  - 169 passed.
- Pytest emitted one non-test-failing cache warning because `.pytest_cache`
  could not be created (`WinError 5`).

## Remaining issues

- The generated View must be exported through CuePlayer and imported on real
  MA3 hardware/onPC to verify widget positions, sizes, visible pool ranges,
  and ViewButton switching end-to-end.
- The trimmed install macro, fixed per-song Sequence block allocation, and
  editable Effect/Group Pool fields still need the previously listed real-
  hardware verification.
- Unconfirmed MA3 pool types remain intentionally unsupported.
- Pre-existing untracked scratch paths were not modified:
  `.codex-test-tmp/`, `.tt-p1/`, `.tt-p2/`, `startup_error.txt`.

## Suggested next task

Run one complete real-hardware/onPC validation export covering Sequence,
Groups, fixed Template EFX, per-song Song EFX, and Macros in the View Layout;
confirm positions/sizes, correct starting pool cells, ViewButton switching,
the trimmed install macro, fixed Sequence blocks, and Effect/Group numbering.
Report the exact result before making any further MA3 XML changes.
