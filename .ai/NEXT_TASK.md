# Next task

**Status:** Queued — Export Options visuals corrected; awaiting real MA2 verification
**Type:** MA Export validation
**Updated:** 2026-08-08

## Current task

Validate per-song Main/Button content selection in a real MA2 import.

## Requirements

- Export a mixed set: one full song, one Main-only song, and one Button-only
  song.
- Confirm Sequence pool allocation, executor assignment, Timecode tracks, and
  generated Views match the selected content.
- Keep the shared 16×8 View editor and current MA2 version support.
- Do not implement Telnet.
- Do not touch `startup_error.txt`.
