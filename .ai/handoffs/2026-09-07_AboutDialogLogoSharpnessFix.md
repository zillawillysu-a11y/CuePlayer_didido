# 2026-09-07 — About Dialog logo sharpness fix

## Task
Narrow UI-hardening task: the Help → About Cue Player dialog's left-side app
logo/icon rendered blurry. Menu structure, About text/content, version,
copyright, splash, EXE metadata, and all playback/timeline systems were
explicitly out of scope and untouched.

## Root cause
`AboutDialog.__init__` (`src/cueplayer/ui/about_dialog.py`) built the logo
with:

```python
pixmap = QPixmap(str(icon_path)).scaled(48, 48, ...)
```

`app_icon_path()` resolves to `src/cueplayer/ui/assets/app_icon.ico`, which
does contain a proper multi-resolution layer set (16/24/32/48/64/128/256 px —
confirmed via `QImageReader.imageCount()` = 7 frames). But `QPixmap(path)`
constructed from an `.ico` only loads the **first** frame — the 16x16 layer —
never the larger ones. That 16x16 pixmap was then stretched up to 48x48 with
`SmoothTransformation`, which is a 3x upscale of a tiny source: guaranteed to
look soft/blurry regardless of DPI.

## Fix
Load the icon as a `QIcon` and ask it for the pixmap at the actual display
size instead of asking `QPixmap` for a fixed frame and scaling it:

```python
icon = QIcon(str(icon_path))
dpr = self.devicePixelRatioF() or 1.0
device_size = round(_LOGO_LOGICAL_SIZE * dpr)  # _LOGO_LOGICAL_SIZE = 48
pixmap = icon.pixmap(device_size, device_size)
pixmap.setDevicePixelRatio(dpr)
```

`QIcon.pixmap()` is multi-resolution-aware: for a `.ico`/`.png` source it
selects (or Qt-side rasterizes, for vector formats) the layer closest to the
requested size instead of blindly returning frame 0, so at 100% DPI it now
picks the ico's exact 48x48 layer, and at higher DPI (125/150/200%) it
requests the correspondingly larger device pixel size (e.g. 96x96 at 200%),
still well inside the ico's available 128/256 layers — no upscaling in any
of the four DPI cases the user asked about. `setDevicePixelRatio()` on the
returned pixmap keeps the on-screen *logical* size unchanged (`QLabel` is
still fixed at 48x48 logical px via `setFixedSize`), so the dialog's overall
layout/size is untouched — only the source layer selection changed.

`app_icon.png` (512x512) exists in the same assets folder but is second in
`app_icon_path()`'s preference order (the `.ico` is checked first and always
wins when present) — not touched, since the `.ico` already contains enough
resolution once queried correctly via `QIcon`.

## Files changed
- `src/cueplayer/ui/about_dialog.py` — `QPixmap` import replaced with the
  already-imported `QIcon`; icon-loading block reworked as above; added
  module-level `_LOGO_LOGICAL_SIZE = 48` constant (display size, unchanged
  from before — sharpness was the only goal, not size).
- `tests/ui/test_about_dialog_and_title.py` — added
  `test_about_dialog_logo_pixmap_is_not_upscaled_from_a_tiny_source`,
  asserting the rendered `QLabel` pixmap's *device*-pixel size (accounting
  for `devicePixelRatio()`) is at least the requested display size, i.e. it
  was never stretched up from a smaller source frame.

## Tests
`.venv/Scripts/python.exe -m pytest tests/ui/test_about_dialog_and_title.py -q`
→ 5 passed (existing 4 + new regression test), offscreen Qt platform.

## Manual verification (for the user)
On the Windows dev machine, at each display scaling level (Settings → Display
→ Scale: 100%, 125%, 150%, 200%), open **Help → About Cue Player** and confirm
the logo in the top-left of the dialog looks crisp (not soft/pixelated) and is
still the same modest size as before (roughly the height of two text lines).
No other change should be visible — Help menu structure, About text, version,
copyright are all unchanged.

## Out of scope / untouched
Help menu structure, About dialog text/layout beyond the icon label's fixed
size, `APP_VERSION`/copyright, splash screen, main window title, EXE metadata,
playback, MTC, LTC, timeline, and all previously-parked candidates in
`.ai/NEXT_TASK.md` (ripple edit, multi-type delete, pre-existing test
failures, etc.) — none were touched this session.
