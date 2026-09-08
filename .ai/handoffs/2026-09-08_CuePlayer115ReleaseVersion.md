# CuePlayer 1.15 Release Version

Date: 2026-09-08. Branch: `cursor/technical-audit-0815-028d`.

## Task objective

Bump the approved Art-Net Timecode build to product version 1.15 for packaging.

## What was implemented

- Canonical version, installer fallback/example, tests, README, and changelog now use
  1.15.
- No functional or schema changes were included.

## Files changed

Version/app identity, Inno Setup, version/UI tests, release docs, report/next/handoff.

## Architecture decisions

`cueplayer.__version__` remains the only canonical product-version authority; project
schema version is unchanged.

## Tests performed

Identity reports `1.15 1.15 (1, 15, 0, 0)` and the targeted version/UI suite passes.

## Remaining issues

Windows zip/Setup artifacts must be rebuilt and smoke-tested by the user.

## Suggested next task

Run `packaging/build_windows.ps1` and verify packaged version plus Art-Net output using
the steps in `.ai/NEXT_TASK.md`.
