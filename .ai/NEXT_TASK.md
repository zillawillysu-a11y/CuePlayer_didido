# Next task

**Status:** Blocked — awaiting real-hardware/onPC validation from Willy
**Type:** Validation (MA3 exporter — Song View / Song Change Workflow)
**Updated:** 2026-08-09

## Do this first

Export one show from CuePlayer with a View Layout containing:

- Sequence
- Groups
- fixed Effects (Template EFX)
- per-song Effects (Song EFX)
- Macros

Import and run it on grandMA3 2.3.2, then report the exact result for:

1. Widget positions and sizes on the 18x10 screen.
2. First visible pool cells for Sequence, Groups, Template EFX, Song EFX,
   and Macros. MA3 XML now derives `ScrollV` from View Layout start/stride.
3. ViewButton switching when Page Change runs.
4. The trimmed install macro completing without Illegal object/property or
   missing steps.
5. Fixed per-song Sequence Pool block reservation.
6. Effect/Group Pool Start + Slots Per Song affecting exported numbers.

Do not change MA3 XML further without an official reference or a real onPC
export demonstrating the required shape/property.

## Explicitly out of scope

- MA2 export logic
- Page/Groups allocation behavior beyond the validation above
- CSV
- video-waveform code
- unconfirmed MA3 ViewWidget pool types

## Scratch files

Pre-existing `.codex-test-tmp/`, `.tt-p1/`, `.tt-p2/`, and
`startup_error.txt` are unrelated untracked scratch files and were not touched.
