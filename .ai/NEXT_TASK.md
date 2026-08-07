# Next task

**Status:** Queued — awaiting human start
**Type:** MA Export PySide6 interface redesign
**Updated:** 2026-08-08
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

## Current task

Replace the legacy ShowPatchPage visual layout with the approved playlist-style PySide6 workflow represented by `design/ma_export_playlist_mockup.html`.

## Required pages

1. Songs & Pools
2. Export Registry
3. Console Setup
4. View Layout
5. Review & Export

## Requirements

- Reuse existing export logic; do not rewrite the MA2/MA3 exporters.
- Reuse production MA2 version detection, output-folder follow/custom mode, and `apply_registry_scan_result`.
- Keep all interface chrome in English and preserve Unicode song display.
- Preserve per-song Main/Button content selection and explicit Song Order.
- Preserve approved defaults and Fixed/Per Song View allocation behavior.
- Keep Screen 3 fixed at 16 × 8 and Pool titles consuming one cell.
- Do not implement Telnet transport in the visual-redesign task.
- Do not touch `startup_error.txt`.

## Done when

The running PySide6 application visibly follows the approved five-page mockup, existing export behavior remains green, and focused UI tests cover page navigation, readable fields, Registry/Setup synchronization, View grid invariants, and export review.
