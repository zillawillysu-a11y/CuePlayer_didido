# Next task

**Status:** Awaiting user validation and packaging
**Type:** Shortcut validation / Release 1.1.3
**Updated:** 2026-08-12

## Do this first

1. Press S and confirm Mark movement mode and S chip toggle together.
2. Press U and confirm Beat Grid magnet snapping and magnet chip toggle together.
3. Click either chip and confirm its keyboard shortcut remains synchronized.
4. Type words containing S and U in a Cue List Note and confirm neither mode
   changes.
5. Rebuild and smoke-test CuePlayer 1.1.3.

## Relevant files

- `src/cueplayer/ui/main_window.py`
- `src/cueplayer/ui/timeline_widget.py`
- `tests/ui/test_setup_mode_shortcut.py`
- `packaging/build_windows.ps1`
