# Shared Executor Page setting

## Task objective

Use one Page field for Main and Button executor allocation.

## What was implemented

- UI Page input generates Main `Page.130` and Buttons `Page.101+`.
- Retained Next Page per song as an optional page increment, while Main and Buttons remain together.
- Kept existing persisted executor values compatible.

## Tests performed

- Focused UI/exporter suite: 18 passed.
- Compile and diff checks passed.

## Remaining issues

- Per-song Main/Button selection is next.
- `startup_error.txt` was not modified.
