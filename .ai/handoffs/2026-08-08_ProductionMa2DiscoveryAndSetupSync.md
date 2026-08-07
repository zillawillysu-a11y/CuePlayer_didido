# Production MA2 Discovery and Setup Sync

## Task objective

Move approved MA2 version, folder, and Registry synchronization behavior from the browser design into the production PySide6 export page.

## What was implemented

- Installed and running onPC version discovery.
- Target Version controls and minimum-version validation.
- Version-following and custom Output Folder modes with native Browse.
- Target/output path mismatch blocking.
- Registry scan result application seam with protected fixed controls.
- Approved MA2 defaults in the domain model and production widgets.

## Files changed

- `src/cueplayer/domain/models.py`
- `src/cueplayer/exporters/ma_default_dirs.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_ma_default_dirs.py`
- `tests/exporters/test_show_patch.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-08_ProductionMa2DiscoveryAndSetupSync.md`

## Architecture decisions

- Existing discovery adapter was extended; no duplicate service was introduced.
- Windows process inspection is read-only and timeout-bounded.
- Telnet transport remains separate from the UI application seam.
- This is a production behavior slice, not the full visual redesign.

## Tests performed

- 29 focused exporter, UI, persistence, and Unicode tests passed.
- Compile and ShowPatchPage offscreen smoke checks passed.
- Actual installed MA2 3.9.63 importexport folder was detected.

## Remaining issues

- Legacy ShowPatchPage layout still needs replacement by the approved five-page design.
- No live Telnet scanner calls the Registry synchronization seam yet.
- Version-family XML fixtures remain incomplete.
- `startup_error.txt` was not modified.

## Suggested next task

Implement the full approved five-page playlist-style PySide6 MA Export interface while preserving the production behavior completed in this task.
