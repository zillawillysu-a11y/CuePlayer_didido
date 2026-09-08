# S1View coordinate and Effect scroll fix

## Task objective

Fix MA2 View placement and Effect first-cell behavior using the user's known-working S1View fixture.

## What was implemented

- Omitted zero `x`/`y` attributes.
- Kept Macro top-row placement as `x=10` without `y=0`.
- Used `Effect Start - 1` for MA2 Effect scroll offset.

## Tests performed

- Focused exporter/UI suite: 18 passed.
- Compile and diff checks passed.

## Remaining issues

- Per-song Main/Button selection is next.
- `startup_error.txt` was not modified.
