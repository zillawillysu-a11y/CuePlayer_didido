# Console Setup UI Fixes and Page Layout Reflow

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

User tested the running desktop app and gave 7 pieces of feedback from real
screenshots, then mid-turn added 3 more page-layout requests. See
`.ai/REPORT.md` for the full breakdown; this file is the durable archive.

## What was implemented

1. Export Queue labels: Chinese name first, English second.
2. **Bug fix**: MA2 export never passed `show_name=` to the exporter, so
   Show Name changes never reached the exported Song List/Template Page
   labels — always silently fell back to "CuePlayer". Fixed in `_export()`.
3. Console Setup: moved Effect/Group/View/Song Macro/Fixed Macro Start out
   of the generic "Export Options" grid into the "Pool Start" box, next to
   Sequence/Timecode.
4. View Layout: added a "Follow Console Setup's per-song Pool Start"
   checkbox per Pool widget (only for sequence/effects/groups/timecode/
   macros types). This *replaces* the old inconsistent one-directional
   View→Console auto-push (which only handled Sequence/Effects and never
   Groups/Timecode/Macro) — that mismatch was the actual cause of the
   Console-Setup-vs-View-Layout number disagreement the user saw.
5. Export-confirm dialog: "Enabled content" is now one bullet per line.
6. Telnet login now defaults to `administrator`/`admin` (grandMA2's stock
   login) instead of blank/`CuePlayerScan`.
7. Page layout reflow (Songs & Pools, Export Registry, Review & Export) —
   each moved from stacked full-width boxes to left/right or
   left/middle/right columns so the data tables get more vertical room.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `src/cueplayer/domain/models.py`
- `src/cueplayer/persistence/project_store.py`
- `tests/ui/test_show_patch_ma2_discovery.py`

## Architecture decisions

The View Layout "follow" feature stays live-synced (recomputed from Console
Setup on every `_write_ui_to_settings()`), not a one-time copy, so later
Console Setup edits can't silently desync a Pool the user opted to follow.
It defaults off/absent on every widget, so existing saved projects and
already-exported Pool numbers are unaffected until the user opts in.

## Tests performed

- `QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python.exe -m pytest tests/ui/test_show_patch_ma2_discovery.py tests/ui/test_setlist_folder_drag.py -q`: **27 passed**.
- `compileall`: passed.
- No way to visually confirm the page-layout reflow in the real desktop app
  from this session — needs the user's own eyes.

## Remaining issues

Item 4 (Manual Pool Starts → per-song, per-column manual override with
collision detection + an auto-fill/auto-sequence button) was investigated
but **intentionally not implemented**. Root finding: Sequence and Timecode
are genuinely per-song fields that flow into the real export, but Effect/
View/Song Macro pools are only ever computed from a single global
start+slots-per-song formula inside the exporter — and Groups doesn't even
appear as an exporter parameter, suggesting it isn't wired into the real
MA2 XML output at all yet. Building full per-song override for all six pool
types safely requires first extending `Ma2Exporter` to accept per-song
assignments instead of a global formula. This is a correctness-critical
change to MA export (PRODUCT_SPEC non-negotiable), so it needs the user's
explicit scope decision before implementation — see `.ai/NEXT_TASK.md`.

## Suggested next task

Get the user's answer on item 4's scope (full six-pool-type override
requiring an exporter change vs. a safer first slice covering only
Sequence/Timecode, which are already genuinely per-song today). Also ask
the user to visually confirm the three page-layout changes in the desktop
app.
