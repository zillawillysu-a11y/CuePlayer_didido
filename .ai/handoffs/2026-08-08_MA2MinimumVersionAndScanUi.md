# MA2 Minimum Version and Scan UI

## Task objective

Set grandMA2 3.3.4.3 as CuePlayer's minimum supported MA2 version and prototype the Telnet live Pool scan connection UI.

## What was implemented

- Added MA2 Host, target version, command/monitor ports, user, and password fields.
- Added Test Connection and Scan Current Show prototype controls/status.
- Added command port 30000 and monitor port 30001 defaults.
- Added 3.3.4.3 as the minimum target in Registry and Console Setup selectors.
- Updated `docs/PRODUCT_SPEC.md` to require 3.3.4.3 through 3.9.63.6 support.
- Updated old reverse-engineering/fixture steps to include both 3.3.4.3 and 3.9.63.6.
- Added `docs/MA2_VERSION_SUPPORT.md` with compatibility and completion rules.
- Extended `docs/MA2_EXPORT_REGISTRY_SPEC.md` with live scan transport requirements.

## Files changed

- `design/ma_export_playlist_mockup.html`
- `docs/PRODUCT_SPEC.md`
- `docs/MA2_VERSION_SUPPORT.md`
- `docs/MA2_EXPORT_REGISTRY_SPEC.md`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-08-08_MA2MinimumVersionAndScanUi.md`

## Architecture decisions

- 3.3.4.3 is a product-wide minimum, not a scanner-only target.
- Compatibility uses verified version profiles; newest-schema fallback is not assumed safe.
- The current connection controls are UI-only and deliberately do not open sockets.
- Production support requires golden fixtures and onPC execution at the minimum version.

## Tests performed

- Parsed embedded JavaScript with Node.
- Verified unique connection-control IDs and event wiring.
- Verified 3.3.4.3, ports 30000/30001, and product-spec references.
- Ran `git diff --check`.

## Remaining issues

- Golden XML/Plugin/View fixtures for 3.3.4.3 are not yet captured.
- Real Telnet framing, login, timeout, disconnect, and noisy-monitor parsing are not implemented.
- Production Registry persistence remains pending.

## Suggested next task

Capture minimum-version MA2 fixtures and validate the Pool Scanner Plugin output on grandMA2 onPC 3.3.4.3 before implementing real Telnet sockets.
