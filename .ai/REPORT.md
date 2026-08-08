# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

User reported that after running a Live Scan the song list numbers did not
move past the Pools already in use on the console, and asked for a button
that pushes every Pool number past the detected maxima, with turning it off
meaning "just export normally".

## What was implemented

### Two real bugs found by reproducing the reported state

Rather than guessing, I reproduced the user's screenshot end-to-end
offscreen. Two independent causes:

1. **`apply_registry_scan_result` never set the Group Pool.** It updated
   Sequence/Effect/Timecode/Song-Macro/View but silently omitted Groups
   entirely, so after a scan the Group Pool still pointed at numbers the
   console was already using. Reproduced: scan applied, Group spinbox
   unchanged at its old value.
2. **Per-song overrides silently outranked the scan.** In the user's
   session an earlier *Auto-Fill & Sequence* had written a hard override
   for every song at 201. Overrides win in `build_show_patch`, so the
   scan's new starts had no effect — the Console Setup spinbox read 509
   while the table still read 201, with nothing in the UI explaining why.
   That exactly matches the screenshot (Sequence 201–220, "Next Sequence
   461", scan max Seq 508). This was a design flaw in the override feature
   I added earlier: it had no visible indication it was active.

### Fixes

- Added the missing `group_start` to `apply_registry_scan_result`, passed
  from `snapshot.next_free("group")` at both scan call sites.
- New **"Start after scanned Pools"** checkbox in Export Registry, next to
  the scan buttons (persisted as `MaExportSettings.ma2_start_after_scanned`).
  Implemented in `build_show_patch` — the single allocation source of truth
  — so it flows to every table, the CSV/TXT report and the real export at
  once. Semantics:
  - **On:** every Pool base start becomes `max(configured, scanned_max + 1)`
    for all six pool types. Never *lowers* a start that is already past the
    scan. Inert when nothing has been scanned yet (with a status hint).
    Stale per-song pins are ignored while on, otherwise the numbers still
    could not move — which was the user's whole problem.
  - **Off:** byte-for-byte the previous behaviour, i.e. a plain export from
    the configured starts, pins honoured again. Verified by a test that
    compares "toggle off" against "never scanned".
- Made the silent-override trap impossible to hit again: the status line
  now states how many songs are pinned by manual overrides and that they
  ignore the scan until the toggle is enabled or Clear All Overrides is
  used.

## Files changed

- `src/cueplayer/domain/models.py`
- `src/cueplayer/persistence/project_store.py`
- `src/cueplayer/exporters/show_patch.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_show_patch.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `tests/persistence/test_schema.py`

## Architecture decisions

The toggle lives in `build_show_patch` rather than in the UI, so no caller
can forget it — the tables, the allocation report and the exporter all read
the same allocation. It clamps upward only (`max(configured, scanned+1)`),
so enabling it can never move an export *backwards* onto lower numbers.

## Tests performed

- Targeted suites (`show_patch_ma2_discovery`, `setlist_folder_drag`,
  `exporters`, `persistence/test_schema`): **123 passed**.
- 8 new tests: Groups moved by a scan; toggle clears all six scanned
  maxima; toggle off is identical to never-scanned; toggle beats stale
  pins and pins return when it is off; never lowers a higher configured
  start; inert without scan data; UI toggle round-trip; settings persistence
  (including that an older project file without the key loads as off).
- **Negative-tested both guards:** reverting the Groups fix fails the Groups
  test; reverting the toggle fails the start-after-scanned tests; restoring
  both passes.
- `compileall`: passed.

## Remaining issues

- `tests/persistence/test_project_bundle.py::test_collect_bundle_layout_and_relative_paths`
  fails intermittently when the whole persistence suite runs together
  (Windows directory-rename lock on a Chinese path). It passes in isolation
  (12/12) and failed the same way earlier in this session before any of
  these changes — unrelated to this diff, which does not touch that file.
- Groups overrides remain planning/report-only in the exporter (unchanged
  limitation, documented in the earlier per-song-override handoff).
- Pre-existing full `tests/ui` suite stack-overflow crash, unrelated.
- `startup_error.txt` and `.codex-test-tmp/` untouched.

## Suggested next task

User re-runs Scan Current Show, ticks **Start after scanned Pools**, and
confirms every column jumps past the scanned maxima; then unticks it and
confirms the numbers return. After that, the still-outstanding item is one
real MA2 export with the toggle on, verifying on the console that nothing
lands on existing show objects.
