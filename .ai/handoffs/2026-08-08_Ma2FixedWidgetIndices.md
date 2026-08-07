# MA2 fixed Widget indices

## Task objective

Prevent MA2 from placing Macro over Sequence after importing a generated View.

## What was implemented

- Fixed XML indices: Fixed Effects 0, Song Effects 1, Sequence 2, Macro 3.
- Preserved editor geometry while honoring MA2's index requirement.

## Tests performed

- Focused exporter/UI suite: 19 passed.
- Compile and diff checks passed.

## Remaining issues

- Per-song Main/Button selection is next.
- `startup_error.txt` was not modified.
