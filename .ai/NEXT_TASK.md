# Next task

**Status:** Awaiting user validation and packaging
**Type:** Shortcut validation / Release 1.1.3
**Updated:** 2026-08-12

## Do this first

1. With Timeline focused, press S and confirm Mark movement mode and the S chip
   both turn on; press S again and confirm both turn off.
2. Edit a Cue List Note containing the letter S and confirm typing does not toggle
   Setup mode.
3. Confirm clicking the S chip and pressing S remain mutually synchronized.
4. Rebuild and smoke-test CuePlayer 1.1.3.

## Relevant files

- `src/cueplayer/ui/main_window.py`
- `src/cueplayer/ui/timeline_widget.py`
- `tests/ui/test_setup_mode_shortcut.py`
- `packaging/build_windows.ps1`
