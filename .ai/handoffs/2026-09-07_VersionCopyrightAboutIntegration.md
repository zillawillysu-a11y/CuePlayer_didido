# 2026-09-07 — Cue Player 1.14 version/copyright/About integration

## Task
Bump the product to **Cue Player 1.14** with copyright
`Copyright © 2026 DiDiDo Design Co., Ltd. All rights reserved.`, and make Splash,
Main Window title, About dialog, and EXE packaging metadata all read one canonical
version/copyright source instead of each hard-coding their own copy. No release
build was performed this session — code/config only, per user instruction.

## Canonical source
- `src/cueplayer/__init__.py` — `__version__ = "1.14"` (unchanged role: the one
  place a future version bump touches).
- `src/cueplayer/app_info.py` (new) — derives everything else from `__version__`:
  `APP_NAME = "Cue Player"`, `APP_VERSION`, `COMPANY_NAME`, `COPYRIGHT_YEAR`,
  `APP_TITLE = f"{APP_NAME} {APP_VERSION}"`, `COPYRIGHT`, and
  `version_tuple()` (parses `"1.14"` → `(1, 14, 0, 0)` for the Windows
  version resource).

**Future version bumps: edit only `src/cueplayer/__init__.py`'s `__version__`.**
Everything below reads it transitively (`app_info` → UI; `pyproject.toml` →
`dynamic = ["version"]` reads `cueplayer.__version__` at build time; `cueplayer.spec`
imports `cueplayer.app_info` at PyInstaller spec-eval time; `build_windows.ps1`
already read `cueplayer.__version__` dynamically before this task and still does).

## Changes

1. **Splash** (`src/cueplayer/ui/splash.py`) — the existing "Cue Player" title
   block (font/size/position) is untouched, per explicit instruction. Added a
   separate low-key footer anchored to the bottom edge (not part of the
   centered title/bar/message block, so it cannot shift that block): small
   `Version 1.14` line, then a dimmer (alpha 160) copyright line below it.
   Both read `cueplayer.app_info.APP_VERSION` / `.COPYRIGHT`. Splash pixmap
   size unchanged (520×300).

2. **Main window title** (`src/cueplayer/ui/main_window.py`) —
   `MAIN_WINDOW_TITLE_PREFIX` now equals `app_info.APP_TITLE` ("Cue Player 1.14")
   instead of the hardcoded `"CuePlayer Main"`. The existing
   `f"{MAIN_WINDOW_TITLE_PREFIX} — {name}{dirty}"` pattern is unchanged, so the
   title bar now reads e.g. `Cue Player 1.14 — MySong *`.

3. **About dialog** (`src/cueplayer/ui/about_dialog.py`, new) — `QDialog` with
   app icon (reuses `cueplayer.util.runtime.app_icon_path()`, no new image
   asset), `APP_NAME`, `Version {APP_VERSION}`, `COPYRIGHT`, one Close button.
   Wired into `main_window.py` via a new `&Help` menu (added after `&View`, so
   it is the rightmost top-level menu) containing `&About Cue Player`. The repo
   had no Help/About menu before this task.

4. **`pyproject.toml`** — switched `[project].version = "1.1.3"` to
   `dynamic = ["version"]` + `[tool.setuptools.dynamic] version = { attr =
   "cueplayer.__version__" }`, eliminating the only stray duplicate version
   literal in the Python packaging metadata.

5. **`packaging/CuePlayer.iss`** — its `#ifndef MyAppVersion` fallback default
   updated to `"1.14"` (comment clarifies `build_windows.ps1` always overrides
   it with `/DMyAppVersion=$Version` read from `cueplayer.__version__`, so this
   fallback only matters if `iscc` is invoked directly without that flag).
   Installer behavior/paths untouched, per instruction.

6. **`packaging/cueplayer.spec`** — added a Windows-only block (before
   `icon_file` resolution) that imports `cueplayer.app_info` and
   `PyInstaller.utils.win32.versioninfo` to build a `VSVersionInfo` object from
   `APP_NAME` / `APP_VERSION` / `COMPANY_NAME` / `COPYRIGHT` /
   `version_tuple()`, wrapped in `try/except` (falls back to `version_info =
   None`, i.e. today's no-metadata behavior, if PyInstaller's versioninfo
   helper or the import path is unavailable — never breaks the build). Passed
   as `EXE(..., version=version_info)`. This produces, once actually built:
   - Product Name / File Description = `Cue Player`
   - Product Version / File Version = `1.14` (and the numeric quad `1.14.0.0`
     in the FixedFileInfo `filevers`/`prodvers`, derived from `version_tuple()`
     — no separate hand-maintained tuple)
   - Company Name = `DiDiDo Design Co., Ltd.`
   - Legal Copyright = `Copyright © 2026 DiDiDo Design Co., Ltd. All rights reserved.`

## Tests added
- `tests/util/test_app_info.py` — canonical constants (`APP_NAME`,
  `APP_VERSION == "1.14"`), `APP_TITLE == "Cue Player 1.14"`, exact `COPYRIGHT`
  string, `version_tuple() == (1, 14, 0, 0)`.
- `tests/ui/test_about_dialog_and_title.py` — `MAIN_WINDOW_TITLE_PREFIX ==
  APP_TITLE`; a real `MainWindow` instance's `windowTitle()` starts with
  `APP_TITLE`; the menu bar's last top-level menu is `Help` and contains an
  `About` action; `AboutDialog`'s labels contain the exact app name, version,
  and copyright strings.
- `tests/ui/test_splash.py` — added
  `test_splash_footer_shows_version_without_moving_bar`: renders the default
  splash pixmap and asserts non-background pixels exist in the bottom ~50px
  band (proof the version/copyright footer painted) while the pixmap stays
  520×300 (proof no layout blowout).

## Test results
`.venv/Scripts/python.exe -m pytest tests/util tests/domain
tests/ui/test_compact_window_min_size.py tests/ui/test_splash.py
tests/ui/test_about_dialog_and_title.py -q` → **183 passed**.

A full `tests/ui` sweep was **not** run: `tests/ui/test_cue_list_playhead_scroll.py`
is a pre-existing, unrelated interpreter hang/crash on this Windows agent
environment (already tracked in `.ai/NEXT_TASK.md` before this session);
per task instructions, did not wait on it. The subset above covers every file
this task touched plus a broad domain/UI baseline sample.

## Startup smoke validation
Offscreen (`QT_QPA_PLATFORM=offscreen`) smoke script: created `QApplication`,
`show_startup_splash`, a real `MainWindow(Project.create("Smoke"))`, and
`AboutDialog(win)`. Result: `window.windowTitle() == "Cue Player 1.14 — Smoke *"`,
`about.windowTitle() == "About Cue Player"`, no exceptions. Confirms the app
boots and every touched surface renders with the new canonical values.

## Packaging metadata validation
PyInstaller is **not installed** in the dev `.venv` on this agent machine (only
installed by `build_windows.ps1` on the actual Windows build machine), so the
`VSVersionInfo` construction inside `cueplayer.spec` could not be executed
end-to-end this session. Verified instead by:
- `cueplayer.app_info.version_tuple()` returns `(1, 14, 0, 0)` (unit-tested).
- Manual re-read of the new spec block confirms every `StringStruct` field
  sources from `app_info` (no literal `"1.14"`/`"Cue Player"`/`"DiDiDo..."` in
  the spec file itself).
- `grep -rn "1\.1\.3"` and a targeted `1.14` sweep across `src/`, `packaging/`,
  `pyproject.toml` (tracked files only — `src/cueplayer.egg-info/` is
  `.gitignore`d stale build metadata) show no leftover duplicate literals.

**Not done this session (explicitly out of scope):** running
`packaging/build_windows.ps1`, invoking PyInstaller, compiling the Inno Setup
installer, or touching any existing `dist/`/release artifact. The next
"Release Build" task should build and eyeball the actual `CuePlayer.exe`
Properties dialog to confirm the resource renders as expected on the real
Windows build machine (dev-venv PyInstaller absence means this is the one part
of the deterministic-test verification not exercised in-process).

## Not touched (per scope)
Playback engine, audio engine timing, MTC thread, LTC mapping/clips, video
sync, Clean Video Output continuity, timeline zoom, MA exporter, song
persistence, waveform, routing, installer behavior/paths, and the previously
completed MTC title-bar-freeze fix (still intact — untouched by this task).

## Follow-up for the user
- Manually eyeball Splash / Main Window title / Help→About dialog in a real
  (non-offscreen) run.
- When ready for a real build: run `packaging\build_windows.ps1` on a Windows
  build machine (produces `dist\CuePlayer\CuePlayer.exe` portable folder,
  `dist\CuePlayer-<version>-<date>-win64.zip`, and — if Inno Setup 7/6 is
  installed — `dist\CuePlayer-Setup-<version>.exe`), then check the .exe's
  Properties → Details tab for Product Name `Cue Player`, Product/File Version
  `1.14`, Company Name `DiDiDo Design Co., Ltd.`, and the copyright string.
