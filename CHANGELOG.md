# Changelog

All notable project changes are recorded here. Product version remains in `pyproject.toml`.

## [Unreleased]

### Sprint 6 — Task 1: MA Export Preflight Domain (2026-08-03)

- Added `domain/validation` (`ValidationReport` / `ValidationIssue` / `ValidationSeverity` / `ValidationCode` / rule registry).
- Docs: `docs/ma_export_validation.md`. Read-only; no export/UI/auto-fix.

### Sprint 6 — Product Planning (2026-08-03)

- Updated `docs/roadmap.md`: post–Align Anchors Top 10, Sprint 6 pick **MA Export Preview / Validation**.
- Docs only — no runtime code.

### Sprint 5 — Align Anchors Beta Stabilization (2026-08-03)

- Preview entry snapshot + Cancel `restore_entry` (position / loops / playing).
- Preview re-enter replaces offset (no accumulate); song-switch ends Preview safely.
- Dialog: Preview banner, variant lock while previewing, Apply re-entrancy + dirty enablement.
- Expanded playback + UI regression tests. No architecture / persistence / engine redesign.

### Sprint 5 — Task 6: Align Anchors Preview Session (2026-08-03)

- PlaybackService ephemeral `begin/update/end_anchor_preview` — never mutates project or undo.
- Align Anchors Preview button auditions draft offset; Cancel/close restores committed mapping.
- Apply still commits via undo command; Song Time + `anchor_mapping` unchanged.

### Sprint 5 — Task 5: Anchor Apply / Commit (2026-08-03)

- Apply writes `draft_offset` → `SongVariant.anchor_offset` via `SetVariantAnchorOffsetCommand`.
- MainWindow pushes undo + marks project dirty; Cancel discards draft; Reset stays draft-only.
- Marks / cue times never move; no Playback / Timeline / Waveform redesign.

### Sprint 5 — Task 4: Anchor Computation (draft only) (2026-08-03)

- `anchor_mapping.offset_from_anchors`; Align Anchors captures song/media anchors and computes draft live.
- Nudge / Reset / preview panel update draft only; Apply remains non-destructive.
- No project mutation, persistence, or playback changes.

### Sprint 5 — Task 3: Align Anchors Dialog Shell (2026-08-03)

- Added `ui/align_anchors_dialog.py` (variant selector, anchor fields, preview placeholder, Apply/Cancel/Reset/Preview stubs).
- Tools → Align Anchors… opens the modal shell; no offset computation or playback changes.
- UX shortcuts wired to stubs; Cancel closes; Apply does not persist.

### Sprint 5 — Task 1: Song-Time Façade Completion (2026-08-03)

- RemoteHost: `seek_song_time` / `song_position` / `song_loop_*` / mapping helpers via PlaybackService.
- Web Remote seek/clock/loops/monitor meta use Song Time; live PCM cursor stays Variant Time.
- MainWindow paste/drop/add-video/cue-list/load transport use `playback.position`.
- No Timeline/Waveform redesign; no Align UI; offset 0 remains identity.

### Sprint 4 — Feature Task 6: Anchor Playback Integration (2026-08-03)

- PlaybackService converts Song Time ↔ Variant Time via `domain.anchor_mapping` on seek / loops / position.
- AudioEngine receives Variant Time only; Timeline playhead bridged back to Song Time.
- Zero-offset / legacy songs unchanged. No Timeline/Waveform redesign; no Align UI.

### Sprint 4 — Feature Task 5: Anchor Mapping Foundation (2026-08-03)

- Added `domain/anchor_mapping.py` (`song_to_variant_time` / `variant_to_song_time`).
- Song Time remains canonical; offsets apply only through the mapping layer.
- Unit tests in `tests/domain/test_anchor_mapping.py`.
- No PlaybackService / Timeline / Waveform / UI changes; offsets not applied at runtime yet.

### Sprint 4 — Feature Task 4: Playback Variant Support MVP (2026-08-03)

- `Song.active_audio_path()` / `replace_main_audio` / `clear_audio_media`.
- `PlaybackService.resolve_active_audio_path` + `active_variant`; ShowSession + MainWindow load helpers retargeted.
- Legacy songs without variants unchanged; single-buffer AudioEngine behavior preserved.
- No UI management, Timeline/Waveform redesign, or anchor-offset application.

### Sprint 4 — Feature Task 3: Song Variant persistence (2026-08-03)

- `SCHEMA_VERSION = 2`; serialize/deserialize `Song.variants` / `selected_variant_id`.
- Migrations isolated in `persistence/project_migrations.py` (Repository stays load/save).
- v1 projects synthesize variants from `audio_tracks` on load; `audio_tracks` still written (Phase A).
- No UI / playback / timeline changes.

### Sprint 4 — Feature Task 2: Song Variant domain foundation (2026-08-03)

- Added `domain/song_variant.py` (`SongVariant`, `VariantKind`) with field docs.
- `Song` gains in-memory `variants` / `selected_variant_id` + selection helpers (not persisted yet).
- Unit tests in `tests/domain/test_song_variant.py`.
- No UI, playback, or schema migration changes.

### Sprint 4 — Feature Task 1: Song Variant design (2026-08-03)

- Added `docs/song_variant_design.md` (domain audit, persistence schema v2 proposal, migration/compat, risks, implementation tasks).
- Updated `docs/roadmap.md` — variants (select one) first; Align/compare later.
- Docs only — no production code.

### Sprint 4 — Feature Planning (2026-08-03)

- Added `docs/roadmap.md` (Top 10 feature candidates, Sprint 4 pick, task plan, extensions).
- Recommended Feature: **Multi-audio Reference lanes + Align Anchors (MVP)**.
- Docs only — no feature implementation.

### Sprint 3.5 — Architecture snapshot (2026-08-03)

- Added `docs/architecture_overview.md` (layer diagram, dependency/service/repository/protocol maps, EventBus + planned taxonomy, MainWindow responsibilities, debt map, Sprint 0→3 progress, Sprint 4 + Feature Sprint candidates, decisions log).
- Updated `docs/current_architecture.md` to point at the snapshot.
- Docs only — no runtime code changes.

### Sprint 3 — Task 3: Event Bus foundation (2026-08-03)

- Added `core/event_bus.py` (`EventBus`: `subscribe` / `unsubscribe` / `publish`).
- Sync in-process only — no async, priorities, sticky/replay, threading, or networking.
- No service migration, no UI changes, no Qt-signal replacement; AudioEngine remains sole clock.
- Updated `docs/current_architecture.md`.

### Sprint 3 — Task 2: Remote boundary foundation (2026-08-03)

- Expanded `ports/remote_host.py` (`RemoteHost` + `RemoteEnginePort`) with member ownership docs.
- Added `web_remote/main_window_remote_host.py` adapter (all MainWindow/engine private access confined here).
- `WebRemoteBridge` now takes `RemoteHost` only — no `host._*` / `engine._*` / monitor-timeline duck-typing.
- MainWindow wires `WebRemoteBridge(MainWindowRemoteHost(self), …)`; networking unchanged.
- Updated `docs/current_architecture.md`.

### Sprint 3 — Task 1: ShowHost Protocol foundation (2026-08-03)

- Added `ports/show_host.py` (`ShowHost` + nested engine/timeline/monitor/video/transport/status Protocols).
- `ShowSessionService` now takes an explicit `ShowHost` (no duck-typed `Any`).
- MainWindow unchanged as structural implementer; no EventBus; Playback/Project untouched.
- Updated `docs/current_architecture.md`.

### Sprint 2 — Task 8: ShowSession foundation (2026-08-03)

- Added `application/show_session_service.py` (activate/deactivate song, prepare playback, timeline/waveform/video refresh coordination, MA3/OSC hook no-op).
- `MainWindow._activate_song` and empty-workspace clear delegate to `ShowSessionService`.
- Playback / Project / Settings services unchanged; no EventBus; AudioEngine/Timeline/Waveform/Video internals unchanged.
- Updated `docs/current_architecture.md`.

### Sprint 2 — Task 7: Settings service foundation (2026-08-03)

- Added `application/settings_service.py` for machine prefs (QSettings, audio device, window/UI session keys, autosave/recent raw keys, fixed theme id).
- `MainWindow` constructs `SettingsService` and routes UI session + audio prefs through it; Project JSON stays out.
- Existing `audio_prefs` schema and keys preserved (no persistence redesign).
- Updated `docs/current_architecture.md`.

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
