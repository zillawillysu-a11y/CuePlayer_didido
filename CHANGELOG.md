# Changelog

All notable project changes are recorded here. Product version remains in `pyproject.toml`.

## [Unreleased]

### Sprint 2 — Task 6: Playback boundary completion (2026-08-03)

- Extended `PlaybackService` with volume / mute / music gain / waveform gain, A–B loop, scrub begin/end, and nudge.
- `MainWindow` no longer writes those playback controls directly to `AudioEngine`.
- `_activate_song` orchestration left in `MainWindow`; AudioEngine / Timeline / Waveform unchanged.
- Device sample-rate (`_playback_rate`) remains engine-internal (not a UI pitch control).
- Updated `docs/current_architecture.md`.

### Sprint 2 — Task 5: Playback foundation (2026-08-03)

- Added `domain/song_session.py` (`SongSession`: current song, playing, position, duration).
- Added `application/playback_service.py` (`PlaybackService`: play/pause/stop/seek/toggle → `AudioEngine`).
- `MainWindow` transport / Space / seek paths go through `PlaybackService`; `current_song` proxies the session.
- AudioEngine / Timeline / Waveform internals unchanged.
- Updated `docs/current_architecture.md`.

### Sprint 1 — Task 4: Repository layer foundation (2026-08-03)

- Added `cueplayer.repository.ProjectRepository` (`load` / `save` / `autosave` / `backup` / `exists`).
- `ProjectService` no longer imports `persistence`; uses the repository instead.
- Existing persistence implementation unchanged (no redesign).
- UI / playback / audio / timeline untouched.
- Updated `docs/current_architecture.md`.

### Sprint 1 — Task 3: Application layer foundation (2026-08-03)

- Added `cueplayer.application.ProjectService` for project lifecycle (new/open/save, dirty, autosave prefs, recent/last projects).
- `MainWindow` delegates lifecycle state and persistence I/O; dialogs, media layout/bundle, and widget apply stay in UI.
- Persistence implementation unchanged (no Repository).
- Updated `docs/current_architecture.md`.

### Sprint 1 — Task 2: Transitional layer cleanup (2026-08-03)

Cleanup only — no UI changes, no behavior changes, no Service/Repository layer.

- **Unified** `cueplayer.ports` onto the working tip (`src/cueplayer/ports/*.py` + `tests/ports/test_ports_package.py`).
- **Removed** `ui.cue_list_columns` compatibility shim; sole import path is `domain.cue_list_columns` (callers + tests retargeted).
- **Removed** unused legacy `playback/clock.py` wall-clock (avoid clash with `ports.clock.PlaybackClock`).
- **Removed** empty stub packages `timeline/` and `ltc/` (real code lives under `ui/` and `timecode/`/`media/`).
- **Removed** unused `_AUDIO_SUFFIXES` re-export alias on `MainWindow`.
- Updated `docs/current_architecture.md`.
- Fixed orphaned test import of deleted UI private `_clamp_channel_ui_text` (collection blocker).

### Sprint 1 — Task 1: Architecture assessment (2026-08-03)

- Added `docs/current_architecture.md` (as-built assessment + Sprint 1 plan). Docs only.

### Sprint 0 (foundation)

- AI workflow (`.ai/`), boundary/migration rules, ports Protocols (architecture line), `cue_list_columns` → domain + temporary UI shim (cleared in Sprint 1 Task 2).
