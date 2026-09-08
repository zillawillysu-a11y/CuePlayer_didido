# Start After Scanned Pools + Group Scan Fix

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

After a Live Scan the allocation did not move past the Pools already in use
on the console. User asked for a button that pushes every Pool number past
the detected maxima, where turning it off means a normal export.

## What was implemented

Reproduced the reported state offscreen first; found two independent causes.

### Bug 1 — the scan never moved the Group Pool

`apply_registry_scan_result` set Sequence/Effect/Timecode/Song-Macro/View
but omitted Groups entirely, so after a scan the Group Pool still pointed at
numbers already in use. Added the missing `group_start` parameter, fed from
`snapshot.next_free("group")` at both scan call sites.

### Bug 2 — per-song overrides silently outranked the scan

An earlier *Auto-Fill & Sequence* had pinned every song at 201. Overrides
win in `build_show_patch`, so the scan's new starts had no effect: the
Console Setup spinbox read 509 while the table still read 201, with nothing
in the UI explaining why. This was a design flaw in the override feature
added earlier — it had no visible indication it was active.

### The requested toggle

New **"Start after scanned Pools"** checkbox in Export Registry, persisted
as `MaExportSettings.ma2_start_after_scanned`. Implemented inside
`build_show_patch` (the single allocation source of truth) so it reaches
every table, the CSV/TXT report and the real export at once.

- **On:** each Pool base start becomes `max(configured, scanned_max + 1)`
  for all six pool types; never lowers a start already past the scan; inert
  when nothing has been scanned; stale per-song pins are ignored while on
  (otherwise the numbers still could not move).
- **Off:** identical to the previous behaviour — plain export from the
  configured starts, pins honoured. Covered by a test comparing "off"
  against "never scanned".

Also surfaced the override count in the status line so the silent-override
trap cannot be hit again.

## Files changed

- `src/cueplayer/domain/models.py`
- `src/cueplayer/persistence/project_store.py`
- `src/cueplayer/exporters/show_patch.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_show_patch.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `tests/persistence/test_schema.py`

## Architecture decisions

The toggle lives in `build_show_patch`, not the UI, so no caller can forget
it. It clamps upward only, so enabling it can never move an export backwards
onto lower numbers.

## Tests performed

- Targeted suites: **123 passed**. 8 new tests covering the Groups fix, all
  six pools clearing the scanned maxima, off == never-scanned, pins beaten
  while on and restored when off, no downward clamp, inert without scan
  data, UI round-trip, and persistence (older files load as off).
- Negative-tested both guards: reverting either fix fails its tests;
  restoring passes.

## Remaining issues

- `test_project_bundle.py::test_collect_bundle_layout_and_relative_paths`
  is flaky on Windows (directory-rename lock on a Chinese path) when the
  whole persistence suite runs together; passes in isolation and fails the
  same way without this diff. Unrelated.
- Groups overrides remain planning/report-only in the exporter (unchanged).
- Pre-existing full `tests/ui` stack-overflow crash, unrelated.

## Suggested next task

User re-scans, ticks Start after scanned Pools, confirms every column jumps
past the scanned maxima and returns when unticked. Then one real MA2 export
with the toggle on, verifying on the console that nothing lands on existing
show objects.
