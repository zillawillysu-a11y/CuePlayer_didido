# Latest AI task report

**Date:** 2026-08-12
**Branch:** `codex/fix-from-1.1.1`

## Task objective

Restore the Video Preview Panel visibility from the state in which CuePlayer
was last closed.

## What was implemented

- Added a machine-local `ui/video_preview_visible` setting.
- View > Video Preview Panel changes persist immediately.
- Startup layout restore applies the saved visibility to both the panel and its
  checked menu action.
- Closing CuePlayer saves the actual panel visibility with the other UI session
  state.
- Existing users without the new key retain the previous default: visible.

## Files changed

- `src/cueplayer/application/settings_service.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_video_preview_layout.py`
- `.ai/REPORT.md`
- `.ai/handoffs/2026-08-12_VideoPreviewVisibilityRestore.md`
- `.ai/NEXT_TASK.md`

## Architecture decisions

- Preview visibility is machine UI state in SettingsService/QSettings, not
  project or Song content.
- Video decode and the shared audio playback clock are unchanged.

## Tests performed

- `tests/ui/test_video_preview_layout.py tests/ui/test_main_window_shutdown.py`
  - 6 passed.

## Remaining issues

- User should close Preview, restart the packaged/source app, and confirm it
  stays closed.

## Suggested next task

Validate Video Preview off/on persistence across two restarts, then rebuild and
smoke-test CuePlayer 1.1.3.
