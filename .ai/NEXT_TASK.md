# Next task

**Status:** Queued — awaiting human start
**Type:** MA2 Windows version discovery
**Updated:** 2026-08-08
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

## Current task

Implement a read-only Windows service that discovers installed grandMA2 onPC versions and the full version of the currently running onPC executable, then expose the result to the production MA Export UI.

## Requirements

- Enumerate `gma2_V_*` installations without modifying MA files.
- Read the running executable's Windows file version when onPC is active.
- Prefer the running full build, otherwise choose the newest supported installed version.
- Preserve manual Target Version selection.
- Reject versions below 3.3.4.3.
- Warn when Target Version, output folder, or later remote scan version disagree.
- Keep the implementation separate from exporter/domain logic and support Unicode Windows paths.
- Do not implement production Telnet scanning in the same task.

## Done when

The service has focused tests for no installation, one/multiple installations, running-version preference, unsupported versions, and path/version mismatch, and the production UI consumes its result.
