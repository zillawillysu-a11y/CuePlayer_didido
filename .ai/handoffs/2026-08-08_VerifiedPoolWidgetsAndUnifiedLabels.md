# Verified Pool widgets and unified labels

## Task objective

Use the user-provided MA2 View fixture to add verified Pool types and eliminate inconsistent black label backgrounds.

## What was implemented

- Parsed `POOLALL.xml` and added verified widget codes for Camera, Filters, Forms, Groups, Images, Layout, Masks, MAtricks, Pages, Timecode, Timecode Slots, Timer, Universes, Views, and Worlds.
- Added the same types to the View Inspector and XML exporter.
- Treated the first three Timecode Pool cells as MA2 built-in slots; they are visible but excluded from numbered per-song capacity.
- Set all form labels to transparent backgrounds for consistent card colouring.

## Tests performed

- Focused UI/persistence/exporter suite: 22 passed.
- Python compile and diff checks passed.
- Offscreen Console Setup screenshot inspected.

## Remaining issues

- Per-song Main/Button export selection is next.
- Telnet remains disabled.
- `startup_error.txt` was not modified.
