# grandMA2 Song View Layout Specification

## Screen 3 invariant

- The usable Screen 3 Pool area is always 16 columns by 8 rows (128 cells).
- This grid size is a fixed product rule and must not be user-configurable.
- Pool windows may move and resize only in complete cells.
- Every Pool window title consumes exactly one cell.
- Visible object capacity is `columns × rows - 1`.

## Shared layout

- CuePlayer uses one shared View layout for all songs.
- Songs do not have independent geometry overrides.
- A song preview changes Pool numbers only; it never changes window geometry.

## Pool allocation modes

- `Fixed`: every song displays the same Pool numbers.
- `Per Song`: Pool numbers advance by Song Order using a configurable reserved-slot stride.
- All generated ranges of the same Pool type must be checked for overlap.
- Visible capacity and reserved slots are separate values. For example, a 16 × 5 window displays 79 objects because its title consumes one cell, while allocation may reserve 80 numbers per song.

## Supported grandMA2 Pool window names

- Camera Pool
- Effects
- Filters
- Forms
- Groups
- Images
- Layout Pool
- Macros
- Masks
- MAtricks
- Pages Channel
- Pages Exec
- Sequence
- Timecode Pool
- Timecode Slots Pool
- Timer
- Views
- Universes
- Worlds

## Default prototype layout

- Sequence: 10 × 1, Per Song, base 1, reserve 20 per song.
- Macros: 6 × 1, Fixed, base 1.
- Effects: 16 × 5, Per Song, base 201, reserve 80 per song.
- Effects: 16 × 2, Fixed, base 1.
