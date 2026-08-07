# MA2 Version Auto Detection Prototype

## Task objective

Add the approved MA2 version auto-detection workflow to the interactive MA Export design.

## What was implemented

- Added a Detect Installed Versions action and detection result row.
- Demonstrated installed-version listing and running-version priority with explicitly prototype-labelled data.
- Kept Target Version manually editable.
- Added minimum 3.3.4.3 validation and target/remote mismatch presentation.
- Added the production detection and authority order to `docs/MA2_VERSION_SUPPORT.md`.

## Files changed

- `design/ma_export_playlist_mockup.html`
- `docs/MA2_VERSION_SUPPORT.md`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-08_MA2VersionAutoDetectionPrototype.md`

## Architecture decisions

- Production Windows discovery must be a read-only adapter/service.
- Local running version is preferred for initial selection; remote version becomes authoritative after connection.
- Output-folder compatibility is always checked before XML generation.

## Tests performed

- HTML JavaScript parse: passed.
- Duplicate ID and required-control checks: passed.
- `git diff --check`: passed before documentation refresh.
- Browser automation could not initialize because the browser connection module was outside the permitted filesystem scope.

## Remaining issues

- Detection is design-only and uses labelled sample data.
- No production Windows discovery or Telnet connection exists yet.
- Compatibility fixtures/onPC verification remain outstanding.
- `startup_error.txt` was not touched.

## Suggested next task

Implement and test the read-only Windows MA2 version discovery service, then wire it into the production MA Export UI without adding Telnet in the same slice.
