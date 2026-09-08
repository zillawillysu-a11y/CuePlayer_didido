# CuePlayer 1.15 Release Version

Date: 2026-09-08. Branch: `cursor/technical-audit-0815-028d`.

## Task objective

Promote the hardware-approved Art-Net Timecode build from 1.14 to CuePlayer 1.15 and
prepare the canonical Windows packaging command for the user.

## What was implemented

- Changed the canonical `cueplayer.__version__` from `1.14` to `1.15`.
- Updated Inno Setup's direct-invocation example and fallback version to 1.15. The
  normal build still receives its version from `cueplayer.__version__`.
- Updated version/title/splash tests, README release status, and changelog.
- No playback, timecode, UI behavior, project schema, or packaging pipeline behavior
  was changed.

## Files changed

- `src/cueplayer/__init__.py`, `src/cueplayer/app_info.py`
- `packaging/CuePlayer.iss`
- `tests/util/test_app_info.py`, `tests/ui/test_about_dialog_and_title.py`,
  `tests/ui/test_splash.py`
- `README.md`, `CHANGELOG.md`
- `.ai/REPORT.md`, `.ai/NEXT_TASK.md`,
  `.ai/handoffs/2026-09-08_CuePlayer115ReleaseVersion.md`

## Architecture decisions

- `src/cueplayer/__init__.py` remains the single version source consumed by Python
  metadata, app title/About/Splash, PyInstaller Windows VersionInfo, artifact names,
  and the Inno command-line define.
- Project schema remains version 3; product release version and persistence schema are
  intentionally independent.

## Tests performed

- Version/App Info/About/Splash suite: passed after updating all 1.14 assertions.
- Direct identity check prints `1.15 1.15 (1, 15, 0, 0)`.
- Repository release-path search has no remaining functional `1.14` references.
- `git diff --check`: passed with only expected CRLF notices.

## Remaining issues

- The Windows zip/Setup artifacts have not been rebuilt in this task; the user will
  run `packaging/build_windows.ps1` on this Windows workstation.
- After building, confirm the executable About/Splash and file properties show 1.15,
  then retain the final Art-Net receiver/PERF evidence with the release artifacts.

## Suggested next task

Run the 1.15 Windows packaging command in `.ai/NEXT_TASK.md`, verify the generated zip
and Setup.exe names, launch the packaged EXE, and confirm Version 1.15 plus Art-Net
Timecode output on the physical receiver.
