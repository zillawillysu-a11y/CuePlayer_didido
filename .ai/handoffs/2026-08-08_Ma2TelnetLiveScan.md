# MA2 Telnet live scan

## Task objective

Implement a read-only live MA2 Pool scanner and synchronize safe starts to
CuePlayer's Export Registry/Console Setup.

## What was implemented

- Added Command Telnet and System Monitor client transport with login,
  timeout, noise-tolerant begin/end frame parsing, and clear failures.
- Added a generated MA2 Plugin named `CuePlayer Live Scan`; it echoes used
  Sequence, Effect, Timecode, Macro, and View numbers without changing the
  show.
- Added Export Registry controls to write the Plugin, test Command Telnet,
  scan the current show, and synchronize next safe starts.
- Persisted Host, ports, and user; password remains session-only.

## Files changed

- `src/cueplayer/exporters/ma2_telnet.py`
- `src/cueplayer/exporters/ma2/exporter.py`
- `src/cueplayer/ui/show_patch_page.py`
- `src/cueplayer/domain/models.py`
- `src/cueplayer/persistence/project_store.py`
- `tests/exporters/test_ma2_telnet.py`
- `tests/exporters/test_show_patch.py`
- `tests/persistence/test_schema.py`
- `tests/ui/test_show_patch_ma2_discovery.py`
- `docs/MA2_TELNET_LIVE_SCAN.md`

## Architecture decisions

- Command Telnet is used only to trigger the Plugin; System Monitor is the
  read channel and carries an explicit CuePlayer frame.
- A scanner error or unsupported version cannot change Pool allocations.

## Tests performed

- Simulated Command/Monitor transport, fragmented/noisy frames, invalid
  frames, Plugin generation, persistence, and offscreen UI: **36 passed**.

## Remaining issues

- Requires a real MA2/onPC test to confirm its System Monitor exposes
  `gma.echo` and that the installed Lua API returns all Pool handles.
- `startup_error.txt` remains untouched.

## Suggested next task

Run the live scanner on MA2/onPC, record the Console/Monitor response, and
adjust only any real-console compatibility differences.
