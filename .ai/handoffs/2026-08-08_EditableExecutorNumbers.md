# Editable executor numbers

## Task objective

Allow Page, Main, and Button Start numbers to be entered separately.

## What was implemented

- Added numeric inputs for Main and Button Start.
- Persisted executor strings are composed as `Page.Main` and `Page.ButtonStart`.
- Existing values are split back into the three UI fields.

## Tests performed

- Focused UI/exporter suite: 19 passed.
- Compile and diff checks passed.

## Remaining issues

- Per-song Main/Button selection is next.
- `startup_error.txt` was not modified.
