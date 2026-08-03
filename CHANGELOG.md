# Changelog

All notable project changes are recorded here. Product version remains in `pyproject.toml`.

## [Unreleased]

### Sprint 1 — Task 2: Transitional layer cleanup (2026-08-03)

Cleanup only — no UI changes, no behavior changes, no Service/Repository layer.

- **Unified** `cueplayer.ports` onto the working tip (`src/cueplayer/ports/*.py` + `tests/ports/test_ports_package.py`).
- **Removed** `ui.cue_list_columns` compatibility shim; sole import path is `domain.cue_list_columns` (callers + tests retargeted).
- **Removed** unused legacy `playback/clock.py` wall-clock (avoid clash with `ports.clock.PlaybackClock`).
- **Removed** empty stub packages `timeline/` and `ltc/` (real code lives under `ui/` and `timecode/`/`media/`).
- **Removed** unused `_AUDIO_SUFFIXES` re-export alias on `MainWindow`.
- Updated `docs/current_architecture.md`.

### Sprint 1 — Task 1: Architecture assessment (2026-08-03)

- Added `docs/current_architecture.md` (as-built assessment + Sprint 1 plan). Docs only.

### Sprint 0 (foundation)

- AI workflow (`.ai/`), boundary/migration rules, ports Protocols (architecture line), `cue_list_columns` → domain + temporary UI shim (cleared in Sprint 1 Task 2).
