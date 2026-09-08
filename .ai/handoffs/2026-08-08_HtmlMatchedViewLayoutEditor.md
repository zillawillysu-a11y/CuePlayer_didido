# HTML-matched View Layout editor

## Task objective

Bring production Console Setup and View Layout in line with the approved HTML design.

## What was implemented

- Compact three-column Console export settings.
- Left-side fixed 16×8 interactive Screen 3 stage and right-side Pool Inspector.
- Whole-cell drag/resize, exact geometry, add/duplicate/delete/reset/lock, song preview, Fixed/Per Song allocations, persistence, and validation warnings.
- Custom Sequence/Effects/Macros geometry and ranges now drive MA2 View XML.

## Tests performed

- Focused suite: 20 passed.
- Compile and diff checks passed.
- 1600×900 production UI screenshots inspected.

## Remaining issues

- Additional MA2 Pool types need real XML fixture codes.
- Per-song Main/Button content selection is next.
- Telnet remains disabled.
- `startup_error.txt` was not modified.
