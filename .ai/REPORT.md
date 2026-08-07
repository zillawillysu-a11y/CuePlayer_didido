# Latest AI task report

**Date:** 2026-08-08
**Branch:** `cursor/video-wave-import-artifact-028d`

## Task objective

Correct MA2 Telnet protocol handling after a real MA2 connection closed after
creating its command line.

## What was implemented

- Changed the Telnet client to issue MA2's required command-line form:
  `Login "<MA2 Show User>" "<password>"`.
- Added minimal Telnet option negotiation before Command or System Monitor
  traffic, so MA2 is not treated as a raw TCP endpoint.
- Rejected missing show users before any command is sent.
- Renamed the UI field to **MA2 Show User** and clarified that its value must
  match an existing, case-sensitive MA2 show user.
- Test Connection now reads and displays a short MA2 command response.

## Files changed

- `src/cueplayer/exporters/ma2_telnet.py`
- `src/cueplayer/domain/models.py`
- `src/cueplayer/persistence/project_store.py`
- `src/cueplayer/ui/show_patch_page.py`
- `tests/exporters/test_ma2_telnet.py`
- `tests/persistence/test_schema.py`
- `docs/MA2_TELNET_LIVE_SCAN.md`

## Architecture decisions

- Command Telnet uses MA2 command-line syntax; raw username/password lines are
  not a valid MA2 login exchange.
- Telnet negotiation explicitly declines optional terminal features that
  CuePlayer does not use.

## Tests performed

- `QT_QPA_PLATFORM=offscreen .venv\\Scripts\\python.exe -m pytest tests\\exporters\\test_ma2_telnet.py tests\\exporters\\test_show_patch.py tests\\persistence\\test_schema.py tests\\ui\\test_show_patch_ma2_discovery.py --basetemp .test-tmp-telnet-negotiate`
- Result: **41 passed** using simulated Command/Monitor sockets.

## Remaining issues

- Retest the real MA2/onPC with a valid MA2 Show User and password, then verify
  the scanner Plugin import path and System Monitor frame.
- `startup_error.txt` remains untouched.

## Suggested next task

Enter a real MA2 Show User/password, click Test Connection, then run
**Import Plugin & Scan** against an empty Plugin Pool and confirm all three
status lights become green.
