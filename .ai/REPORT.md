# CuePlayer 1.16 Release Version

Date: 2026-09-09. Branch: `cursor/technical-audit-0815-028d`.

## Task objective

Close the hardware-verified grandMA3 2.5 destination fix and bump CuePlayer to 1.16
for Windows packaging.

## What was implemented

- Changed the canonical application version from 1.15 to 1.16.
- Updated Inno Setup fallback/example metadata and release-facing README text.
- Updated version, title, Splash, About, and Windows tuple assertions.
- Recorded that the corrected zero-based MA3 2.5 handles passed real-console verification.

## Files changed

Canonical version/app-info files, packaging metadata, release README, version/UI tests,
report, handoff, and next-task documentation.

## Architecture decisions

`cueplayer.__version__` remains the canonical version authority. PyInstaller and the
normal packaging script derive version metadata and filenames from it. No playback,
audio, MTC, LTC, Art-Net, or exporter behavior changed in this release bump.

## Tests performed

- Version and related exporter/UI suite: **23 passed**.
- Runtime identity: `1.16 1.16 (1, 16, 0, 0)`.
- Git diff check passed.

## Remaining issues

Build the Windows zip/installer and smoke-test the packaged executable before distribution.

## Suggested next task

Package CuePlayer 1.16 on Windows and smoke-test launch, audio playback, Art-Net TC,
MTC, and one MA3 2.5 Full Export from the packaged executable.
