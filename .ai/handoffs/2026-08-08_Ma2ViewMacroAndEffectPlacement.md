# MA2 View Macro and Effect placement

## Task objective

Fix exported MA2 View positions after the interactive layout editor exposed widget-specific XML behavior.

## What was implemented

- Macro widgets now retain their configured `x`/`y`, use focus attributes, and have no scroll attributes.
- Effect widgets use MA2's fixed `start - 81` scroll baseline, so Effect Start 201 displays 201 even when the widget is resized.

## Tests performed

- Focused exporter/UI suite: 18 passed.
- Compile and diff checks passed.

## Remaining issues

- Per-song Main/Button selection is next.
- `startup_error.txt` was not modified.
