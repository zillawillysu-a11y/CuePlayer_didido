# Console Setup Review Integration Handoff

## Task objective

Integrate Console Setup and Review & Export into one top-level workflow stage,
preserve high-numbered Pool IDs during Live Scan, and include Group Pool data.

## What was implemented

- Top-level workflow now has four stages; stage 3 is `Console Setup & Review Export`.
- Stage 3 contains nested `Console Setup` and `Review & Export` tabs.
- View Layout navigation opens the Review & Export nested tab.
- Scanner output is chunked and parser aggregation supports repeated Pool lines.
- Group Pool IDs are scanned and their count is shown after a valid scan.

## Files changed

- `src/cueplayer/ui/show_patch_page.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `src/cueplayer/exporters/ma2_telnet.py`
- `tests/exporters/test_ma2_telnet.py`

## Architecture decisions

The existing setup/review pages and controls are reused without duplicating
state or export logic.

## Tests performed

Python module import passed. MA2 Telnet tests: 13 passed. UI tests were blocked
by Windows Temp permissions.

## Remaining issues

Verify the combined UI manually and scan a show containing Effect/Group IDs
above 600.

## Suggested next task

Open Show Patch and verify nested tabs and navigation.
