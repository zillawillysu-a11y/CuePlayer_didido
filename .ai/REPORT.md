# grandMA3 2.3/2.4/2.5 Export Profiles

Date: 2026-09-09. Branch: `cursor/technical-audit-0815-028d`.

## Task objective

Add a selectable, persisted MA3 export-version field while retaining old XML handles
for 2.3/2.4 and using the TC301-proven syntax for 2.5+.

## What was implemented

- Added 2.3, 2.4, and 2.5+ selectors to Show Patch and single-song Export.
- Persisted `ma3_export_version`; legacy projects default to 2.4 compatibility.
- 2.3/2.4 retain DataVersion 2.4.2.2 and `.5.<pool-1>` handles.
- 2.5 uses DataVersion 2.5.0.3 and `.6.<actual sequence pool>` handles.
- Main Go+ and Button Top both retain explicit CueDestination and numeric destination.
- Sequence and Timecode XML use the selected 2.5 DataVersion where plan-aware.

## Files changed

Domain/persistence/export-plan/MA3 exporter, both export UIs, exporter tests,
`docs/MA3_XML_PROFILES.md`, report, handoff, and next task.

## Architecture decisions

Version semantics live in `MaExportProfile`/`Ma3Exporter`, not UI XML logic. Existing
projects remain 2.4; new settings default to 2.5. MA2 is untouched.

## Tests performed

Exporter + persistence + Show Patch UI: **291 passed**. Compileall passed.

## Remaining issues

Import one 2.5+ CuePlayer export into grandMA3 2.5.0.3 and re-export it for canonical
comparison. The collected TC301 source file is external evidence, not committed.

## Suggested next task

Hardware-import a 2.5+ full export and timecode-only re-export; verify Main Go+ and
Button Top destinations, then compare the console re-export against CuePlayer XML.
