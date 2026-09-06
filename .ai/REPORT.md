# Cue Player 1.14 version / copyright / About integration

Date: 2026-09-07. Branch: `technical-audit-0815-028d`. Baseline: `fe50976`. Status: complete
(code/config only — no release build performed, per instruction).

## Task objective

Set the product to **Cue Player 1.14**, copyright
`Copyright © 2026 DiDiDo Design Co., Ltd. All rights reserved.`, and integrate it so
Splash, Main Window title, a new About dialog, and Windows EXE packaging metadata all
read one canonical version/copyright source — no per-file hardcoded duplicates. Do not
touch playback/audio/MTC/LTC/video-sync/timeline-zoom/exporters/persistence/routing, and
do not run an actual PyInstaller/Inno Setup build this session.

## Audit findings (before implementing)

- Canonical-ish source already existed: `src/cueplayer/__init__.py` → `__version__ =
  "1.1.3"`. No `constants.py`/`version.py`/app-wide info module existed yet.
- Two independent hardcoded duplicates of that version string: `pyproject.toml`
  (`[project].version`) and `packaging/CuePlayer.iss`'s `#ifndef` fallback default.
  `packaging/build_windows.ps1` already read `cueplayer.__version__` dynamically for its
  zip filename and the `iscc /DMyAppVersion=` override — no fix needed there.
- `packaging/cueplayer.spec`'s `EXE(...)` had **no** `version=` kwarg at all — the built
  .exe currently ships with empty Windows file-properties metadata (no Company/Copyright/
  Product Version).
- Main window title (`main_window.py`) used a hardcoded `MAIN_WINDOW_TITLE_PREFIX =
  "CuePlayer Main"`, no version shown.
- Splash (`ui/splash.py`) custom-paints `"CuePlayer"` via `QPainter`, no version/copyright.
- No Help menu, no About dialog existed anywhere in the repo.
- Full audit detail: `.ai/handoffs/2026-09-07_VersionCopyrightAboutIntegration.md`.

## Implementation

New canonical module `src/cueplayer/app_info.py` derives `APP_NAME`, `APP_VERSION`
(from `cueplayer.__version__`), `COMPANY_NAME`, `COPYRIGHT_YEAR`, `APP_TITLE`,
`COPYRIGHT`, and `version_tuple()` (Windows 4-int version quad, parsed — not
hand-maintained). `__version__` bumped to `"1.14"`.

- Splash: added a low-key `Version 1.14` / copyright footer anchored to the bottom
  edge, independent of the existing centered title/bar/message block — that block's
  font/size/position is untouched, and the 520×300 pixmap size is unchanged.
- Main window title: `MAIN_WINDOW_TITLE_PREFIX` now reads `app_info.APP_TITLE`
  (`"Cue Player 1.14"`) instead of a hardcoded string; the existing
  `f"{prefix} — {name}{dirty}"` suffix pattern is unchanged.
- New `src/cueplayer/ui/about_dialog.py` (`AboutDialog(QDialog)`): app icon (reused,
  no new asset), name, version, copyright, one Close button. Wired into a new `&Help`
  menu — the rightmost top-level menu — via `&About Cue Player`.
- `pyproject.toml`: `version = "1.1.3"` → `dynamic = ["version"]` reading
  `cueplayer.__version__`, removing that duplicate literal.
- `packaging/CuePlayer.iss`: fallback default synced to `"1.14"` (comment explains
  `build_windows.ps1` always overrides it dynamically); installer behavior/paths
  untouched.
- `packaging/cueplayer.spec`: new Windows-only block builds a `VSVersionInfo` from
  `cueplayer.app_info` (Product/File Name, Product/File Version, Company Name, Legal
  Copyright, numeric version quad from `version_tuple()`), passed to `EXE(version=...)`;
  wrapped in `try/except` so a missing PyInstaller versioninfo helper never breaks the
  build (falls back to today's no-metadata behavior).

## Tests

- `tests/util/test_app_info.py` (new): constants, `APP_TITLE`, exact `COPYRIGHT`,
  `version_tuple()`.
- `tests/ui/test_about_dialog_and_title.py` (new): main window title prefix/instance,
  Help menu is rightmost and contains About, About dialog's labels match canonical text.
- `tests/ui/test_splash.py`: added a regression test that the version/copyright footer
  paints (non-background pixels in the bottom band) while pixmap size stays 520×300.

Result: `pytest tests/util tests/domain tests/ui/test_compact_window_min_size.py
tests/ui/test_splash.py tests/ui/test_about_dialog_and_title.py -q` → **183 passed**.
Full `tests/ui` sweep skipped — `test_cue_list_playhead_scroll.py` is a pre-existing,
unrelated interpreter hang on this Windows agent (already tracked in `NEXT_TASK.md`);
not caused by, or relevant to, this task.

## Startup + packaging validation

Offscreen smoke script instantiated a real `QApplication`, `show_startup_splash`,
`MainWindow(Project.create("Smoke"))`, and `AboutDialog` — no exceptions;
`window.windowTitle() == "Cue Player 1.14 — Smoke *"`, `about.windowTitle() == "About
Cue Player"`.

PyInstaller is not installed in the dev `.venv` on this agent (only installed by
`build_windows.ps1` on the real Windows build machine), so the `VSVersionInfo`
construction could not be executed end-to-end in-process this session; verified
instead via `version_tuple()` unit test, manual re-read of the spec block (every
`StringStruct` sources from `app_info`, no literals), and a repo-wide grep confirming
no leftover `"1.1.3"` / duplicate `"1.14"` in tracked files. **No PyInstaller build,
Inno Setup compile, or release artifact was produced this session** — that is the next,
separate "Release Build" task, to run on the real Windows build machine and confirm the
built .exe's Properties dialog.

## Files changed

`src/cueplayer/__init__.py`, `src/cueplayer/app_info.py` (new),
`src/cueplayer/ui/about_dialog.py` (new), `src/cueplayer/ui/main_window.py`,
`src/cueplayer/ui/splash.py`, `pyproject.toml`, `packaging/CuePlayer.iss`,
`packaging/cueplayer.spec`, `tests/util/test_app_info.py` (new),
`tests/ui/test_about_dialog_and_title.py` (new), `tests/ui/test_splash.py`.
