# Registry Console Setup Sync

## Task objective

Synchronize Registry scan results into Console Setup and add version-aware Output Folder selection to the MA Export mockup.

## What was implemented

- Version detection updates Console and the version-following Output Folder.
- Successful scan results update the next safe Sequence, Effects, Timecode, Song Macro, and View starts.
- Fixed Macro, Template Page, and executor settings are preserved.
- Browse, manual path, and Use Version Default folder modes were added.
- Console Setup now displays scan source, host, remote version, and applied starts.

## Files changed

- `design/ma_export_playlist_mockup.html`
- `docs/MA2_EXPORT_REGISTRY_SPEC.md`
- `docs/MA2_VERSION_SUPPORT.md`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-08_RegistryConsoleSetupSync.md`

## Architecture decisions

- Synchronization is explicit and only follows successful validation.
- Scanned allocations cannot overwrite fixed control configuration.
- A custom Output Folder is user-owned until Use Version Default is selected.

## Tests performed

- HTML JavaScript parse: passed.
- Duplicate ID check: passed with 68 unique IDs.
- Required synchronization and folder-selection wiring: passed.
- `git diff --check`: passed before documentation refresh.

## Remaining issues

- This remains a browser design prototype.
- Production Windows discovery, directory dialog, persistence, and Registry scan input are not implemented.
- Telnet is intentionally outside this slice.
- `startup_error.txt` was not touched.

## Suggested next task

Implement the production Windows version/output-folder discovery adapter and Registry-to-Console-Setup synchronization with focused tests, excluding Telnet transport.
