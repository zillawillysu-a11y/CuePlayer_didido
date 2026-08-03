# CuePlayer — Current Architecture Assessment

**Status:** Sprint 4 Feature Task 3 complete (Song Variant persistence)  
**Updated:** 2026-08-03  
**Scope tip:** `cursor/sprint4-song-variant-persistence-028d`  
**Constraint (Task 3):** Persistence only — no UI/playback/timeline changes; Repository load/save only.

Related docs (do not treat as identical):

| Doc | Role |
|-----|------|
| [`song_variant_design.md`](song_variant_design.md) | **Song Variants domain/persistence design** |
| [`roadmap.md`](roadmap.md) | Sprint 4 Feature Planning + progress |
| [`architecture_overview.md`](architecture_overview.md) | Sprint 3.5 snapshot — layers, maps, risks |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Short aspirational layer diagram |
| [`ARCHITECTURE_REVIEW.md`](ARCHITECTURE_REVIEW.md) | Earlier as-built review (ZH); partially stale |
| [`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md) | Strangler target layout |
| [`BOUNDARY_RULES.md`](BOUNDARY_RULES.md) / [`MIGRATION_RULES.md`](MIGRATION_RULES.md) | Permanent law |
| [`SPRINT_0_REVIEW.md`](SPRINT_0_REVIEW.md) | Foundation retrospective |
| [`CHANGELOG.md`](../CHANGELOG.md) | Release / sprint notes |
| **This file** | Living English as-built assessment + per-task notes |

---

## Sprint 1 Task 2 — Transitional cleanup (done)

| Action | Result |
|--------|--------|
| Unify `ports/` | Canonical `src/cueplayer/ports/*.py` + `tests/ports/test_ports_package.py` on this tip |
| Remove `ui.cue_list_columns` shim | Callers → `domain.cue_list_columns` only; shim file deleted |
| Remove dead `playback/clock.py` | Unused wall-clock `PlaybackClock` (name clash with `ports.clock.PlaybackClock`) |
| Remove empty `timeline/` / `ltc/` stubs | Real timeline UI under `ui/`; LTC under `timecode/` + `media/` |
| Drop `_AUDIO_SUFFIXES` alias | Use `AUDIO_SUFFIXES` from `ui.drag_drop` only |

**Not done in Task 2:** Service Layer, Repository pattern, RemoteHost wiring, adapters renames.

---

## Sprint 1 Task 3 — Application layer foundation (done)

| Action | Result |
|--------|--------|
| `application/project_service.py` | New/open/save/save-as helpers, dirty, autosave prefs, recent/last project |
| MainWindow | Delegates lifecycle state + I/O; keeps dialogs, media layout/bundle, engine stop, apply_project |
| Persistence | Unchanged (`load_project` / `save_project` / backup) |
| Recent projects | QSettings list (max 10) + legacy last-project key for session restore |

**Not done here:** Repository pattern, RemoteHost, other application services.

---

## Sprint 1 Task 4 — Repository layer foundation (done)

| Action | Result |
|--------|--------|
| `repository/project_repository.py` | `load` / `save` / `autosave` / `backup` / `exists` |
| `ProjectService` | Depends on repository only (no `persistence` imports) |
| Persistence | Unchanged; repository wraps existing functions |
| UI | Unchanged |

Dependency:

```text
MainWindow → ProjectService → ProjectRepository → persistence.project_store / backup
```

**Not done here:** PlaybackService, RemoteHost, generic repository framework.

---

## Sprint 2 Task 5 — Playback foundation (done)

| Piece | Role |
|-------|------|
| `domain/song_session.py` (`SongSession`) | Current song + playing / position / duration snapshot |
| `application/playback_service.py` (`PlaybackService`) | Play / Pause / Stop / Seek / Toggle → `AudioEngine` |
| MainWindow | Transport + Space wired to `PlaybackService`; `current_song` proxies session |

### Design contracts (Task 5)

**SongSession** — Current song + transport snapshot mirror.

**PlaybackService** — Play/Pause/Stop/Seek/Toggle → engine; sync session.

See Task 6 for expanded PlaybackService contract (volume/loop/scrub/nudge).

### Architecture before / after

```text
Before:
  MainWindow ──play/pause/stop/seek──► AudioEngine
  MainWindow.current_song (local field)

After:
  MainWindow ──► PlaybackService ──► AudioEngine  (sole sample clock)
                     │
                     └─ syncs ► SongSession (current song + transport snapshot)
  MainWindow.current_song ──property──► SongSession.song
```

**Deferred from Task 5 (done in Task 6):** volume / loop / scrub / nudge boundary.

---

## Sprint 2 Task 6 — Playback boundary completion (done)

| Piece | Role |
|-------|------|
| `PlaybackService` (extended) | Volume / mute / music gain / waveform gain; A–B loop; scrub begin/end; nudge |
| `SongSession` | Unchanged contract — transport read-model mirror only |
| MainWindow | No longer writes volume/loop/scrub/nudge to `AudioEngine` directly |
| `_activate_song` | Still in MainWindow (orchestration intentionally deferred) |

### Design decisions

| Decision | Responsibility | Non-responsibility | Dependency | Why |
|----------|----------------|--------------------|------------|-----|
| Volume/mute/gain on `PlaybackService` | Façade writes → engine | Not clip-local video volume UI state | `AudioEngine` | Same path as transport; UI must not touch mix gains |
| Loop mutations on `PlaybackService` | A/B/region/enable/clear + fresh-pair rule | Timeline paint / transport widgets | `AudioEngine` | Preserves engage/`_loop_engage` semantics without engine redesign |
| Scrub begin/end on `PlaybackService` | Pause-for-scrub / resume | VideoSync scrubbing flag (still UI) | `AudioEngine` | Engine owns scrub resume state |
| Nudge on `PlaybackService` | Frame-step seek | Hold-acceleration timing (still UI) | `AudioEngine` | Playback-related seek |
| Playback rate **not** extracted | — | Device `_playback_rate` stays inside engine | — | Not a MainWindow-owned pitch control; PortAudio negotiation only |
| `_activate_song` stays | — | Song load / buffer / timeline apply | MainWindow | Orchestration spans UI surfaces; separate future task |

### Playback dependency graph

```text
Before (Task 5):
  MainWindow ──transport──► PlaybackService ──► AudioEngine
  MainWindow ──volume/loop/scrub/nudge──► AudioEngine   (still direct)

After (Task 6):
  MainWindow ──transport/volume/loop/scrub/nudge──► PlaybackService ──► AudioEngine
  MainWindow ──_activate_song / buffer / device / LTC──► AudioEngine   (orchestration + I/O)
  SongSession ◄── sync (playing/position/duration) ── PlaybackService
```

**Not done here (Task 6):** ShowSessionService; RemoteHost mute path; sync-calib dialog engine mute; `_activate_song` extract.

---

## Sprint 2 Task 7 — Settings service foundation (done)

| Piece | Role |
|-------|------|
| `application/settings_service.py` | Machine prefs façade over `QSettings` + `audio_prefs` |
| MainWindow | Creates `SettingsService`; UI session / audio go through it; no longer owns raw QSettings construction for prefs |
| `ProjectService` | Still owns recent/autosave *orchestration*; uses SettingsService as `SettingsStore` |
| Project JSON | Untouched — must not enter SettingsService |

### Design decisions

| Decision | Responsibility | Non-responsibility | Dependency | Why |
|----------|----------------|--------------------|------------|-----|
| SettingsService owns machine QSettings | Org/app store + key constants | Project song/mark/setlist JSON | `QSettings` | Single machine-state owner |
| Audio via existing `audio_prefs` | load/save/apply overlay | Schema redesign; engine apply | `persistence.audio_prefs` | Identical schema + behavior |
| Window / chrome keys on service | Geometry, splitters, view mode, NOW/cue list | Widget layout logic | Same string keys as before | Move QSettings out of MainWindow without UI redesign |
| Theme = fixed `pitch_black` | Report theme id | Persisted theme switch (none exists) | `THEME_ID` constant | No schema to invent |
| Autosave / recent APIs on service | Raw machine keys | Existence filtering / open-save side effects | Shared keys with ProjectService | Machine vs project separation; ProjectService still orchestrates |
| Project state stays out | — | Never write show content to QSettings | — | Hard architecture rule |

### Settings flow (after Task 7)

```text
MainWindow → SettingsService → QSettings (CuePlayer/CuePlayer)
                 ├─ audio_prefs load/save/apply (machine audio)
                 ├─ ui/* / mainwindow/* / clean_output/* keys
                 ├─ autosave/* + session/recent|last keys (raw)
                 └─ theme_id() → "pitch_black" (code theme; no key)
MainWindow → ProjectService(SettingsService) → recent/autosave orchestration + ProjectRepository
Project JSON ← persistence (project state only)
```

**Still outside SettingsService (debt):** `web_remote.prefs`, `color_presets`, export dialog dirs.

---

## Sprint 2 Task 8 — ShowSession foundation (done)

| Piece | Role |
|-------|------|
| `application/show_session_service.py` | Activate / deactivate song; prepare playback; coordinate timeline / waveform / video refresh |
| MainWindow | Thin `_activate_song` / empty-workspace wrappers; still owns media caches & async loaders |
| `PlaybackService` | Transport / loop only (unchanged) |
| `notify_external_sync()` | No-op extension point for future MA3 / OSC |

### Design decisions

| Decision | Responsibility | Non-responsibility | Dependency | Why |
|----------|----------------|--------------------|------------|-----|
| ShowSessionService owns activate orchestration | Song switch step order | Transport play/pause; project I/O; QSettings | Host + PlaybackService | MainWindow must not coordinate this workflow |
| Host remains MainWindow | Widgets, audio caches, `_load_audio_path` | Service must not import `ui.*` | Duck-typed host | Preserve identical loaders without redesign |
| `prepare_playback` = set_song + timebase | Attach song to clock | Device open / play | `AudioEngine` via host | Clock attach ≠ transport |
| Deferred monitor via QTimer | Same as prior UI | EventBus | Qt | Behavior identical; no EventBus this task |
| `notify_external_sync` empty | Future MA3/OSC hook | Implementing consoles now | — | Extension point only |

### Coordination graph

```text
MainWindow._activate_song
    └── ShowSessionService.activate_song_at
            ├── PlaybackService.clear_loop
            ├── timeline / video_sync / monitor (via host)
            ├── AudioEngine.set_song + timebase + quiesce/buffer (via host)
            ├── host async audio / waveform loaders
            └── notify_external_sync()  (no-op)
```

**Still in MainWindow:** media warm/BPM jobs, dialogs, RemoteHost, mark editing, `_load_audio_path` implementation.

---

## Sprint 3 Task 1 — ShowHost Protocol foundation (done)

| Piece | Role |
|-------|------|
| `ports/show_host.py` | Explicit `ShowHost` + nested surface Protocols |
| `ShowSessionService` | Constructor typed as `ShowHost` (no longer `Any`) |
| MainWindow | Unchanged implementer (structural); no redesign |

### Why each Protocol member exists

Documented in `ports/show_host.py` docstrings. Summary:

| Member group | Why |
|--------------|-----|
| `project` / `current_song` | Activate needs setlist index + bind current song |
| `engine` (+ quiesce/set_song/timebase/buffer/duration) | Sole clock attach without importing AudioEngine |
| `timeline` / `monitor` / `video_sync` / `transport` / `status` | Surface refresh coordination only |
| `_audio_load_token` / `_song_activate_gen` | Cancel in-flight loads; ignore stale deferred monitor |
| `_timeline_ltc_exclude` / `_media_warm_active` | Waveform/LTC display during load |
| `_sync_*` / `_arm_*` / `_load_*` / `_apply_*` / `_refresh_*` | Host-owned helpers called by activate (names kept for no service redesign) |

### Intentionally excluded

Menus, dialogs, undo, setlist edits, BPM, media-warm jobs, RemoteHost, Settings UI, export, PlaybackService transport, ProjectService I/O, optional `_show_video_track_action` (soft `getattr`).

### Remaining duck-typed dependencies

- `getattr(host, "_show_video_track_action", None)` soft optional inside ShowSessionService
- ShowHost still lists private `_` helper names (transitional until host façade methods)
- Web Remote private MainWindow access moved behind `MainWindowRemoteHost` (Task 2)

---

## Sprint 3 Task 2 — Remote boundary foundation (done)

| Piece | Role |
|-------|------|
| `ports/remote_host.py` | Explicit `RemoteHost` + `RemoteEnginePort` |
| `web_remote/main_window_remote_host.py` | Adapter: all MainWindow / engine private access lives here |
| `web_remote/bridge.py` | Typed `host: RemoteHost` only — no `host._*`, no `engine._*`, no `host.monitor/timeline/status` |
| MainWindow | Constructs `WebRemoteBridge(MainWindowRemoteHost(self), …)` |

### Dependency graph before / after

```text
Before:
  WebRemoteServer / WebRTC
       └── WebRemoteBridge ──duck──► MainWindow._private + engine._private
                                    (+ host.monitor / timeline / status)

After:
  WebRemoteServer / WebRTC          (unchanged networking)
       └── WebRemoteBridge ──RemoteHost──► MainWindowRemoteHost
                                                └── MainWindow privates
                                                └── engine privates (listen helpers)
```

### Why each Protocol member exists

Full member docs live in `ports/remote_host.py`. Summary:

| Member group | Why it exists | Subsystem owner |
|--------------|---------------|-----------------|
| `project` / `current_song` / getters | Setlist + mark ops need domain reads | UI session / SongSession |
| `get_playback_clock` / `engine` (`RemoteEnginePort`) | Transport state + play/pause/seek/mute without importing AudioEngine | Playback (AudioEngine today) |
| `mark_dirty` / `refresh_*` / `show_status` | Keep PC chrome + dirty flag in sync after remote edits | MainWindow chrome |
| Loop `set_loop_*` / `clear_loop` | Remote A–B controls mirror desktop loop UI | PlaybackService via MainWindow |
| `activate_song` / `rebuild_song_list` / `selected_song_indexes` | Setlist navigation + folder collapse refresh | ShowSession + setlist UI |
| Marks / undo / digit shortcuts / display apply | Remote mark manager + lane edits | MainWindow mark editing + timeline/monitor |
| Waveform / stand-in / LTC helpers | Remote wave overview matches Music lane | Timeline + media caches |
| `video_listen_*` / `playback_sample_rate` / `sync_video_output_active` | Listen + preview without second decoder | Mixer + video sync |

### Intentionally excluded (other MainWindow methods)

Menus, dialogs, BPM jobs, export, Settings UI, ProjectService I/O, ShowSession internals / ShowHost private loader tokens, EventBus, full AudioEngine construction, networking (HTTP/WebRTC stay in `web_remote`), redesign of remote ops.

### Remaining MainWindow private access from Web Remote

- **None in `bridge.py`.** All private `_` access is confined to `MainWindowRemoteHost`.
- Adapter still calls MainWindow helpers (`_mark_dirty`, `_activate_song`, `_add_mark`, …) and engine internals (`_video_mixer`, `_playback_rate`, `_song`) — that is intentional transitional debt until those become public façades / PlaybackService paths.

### Remaining duck-typed boundaries

- Adapter wraps `window: Any` (not typed as MainWindow — avoids UI import cycles in ports).
- Soft `getattr` inside adapter for optional video stand-in / sync helpers.
- ShowHost private `_` names (separate seam; unchanged this task).

### Remaining protocol technical debt

- `RemoteEnginePort` still exposes a wide engine surface (`buffer`, apply settings) used by state builders — not yet a narrow DTO.
- Video listen still reaches mixer via engine privates inside the adapter.
- Loop / mute remote paths still go MainWindow helpers / engine rather than exclusively `PlaybackService` (behavior preserved).
- `push_song_undo(command: Any)` accepts undo command objects without a typed port.

---

## Sprint 3 Task 3 — Event Bus foundation (done)

| Piece | Role |
|-------|------|
| `core/event_bus.py` | In-process `EventBus`: `subscribe` / `unsubscribe` / `publish` |
| `core/__init__.py` | Re-exports `EventBus` |
| Call sites | **None yet** — infrastructure only |

### Why EventBus exists

MainWindow still fans out dirty / marks / chrome refresh via private helpers and
direct widget calls. A tiny typed bus is the strangler seam for **future**
publish/subscribe without growing that hub further — and without inventing a
second playback clock.

### Problems it is intended to solve (after adoption)

- Decouple services from concrete UI refresh call sites
- Let multiple observers (desktop chrome, later remote) share one event contract
- Unit-test notification wiring without constructing MainWindow

### Problems it intentionally does NOT solve yet

- Playhead / transport / sample clock (stays on `AudioEngine`)
- Async, queued, cross-thread, sticky, replay, priorities, networking
- Replacing Qt widget signals for local UI wiring
- Migrating PlaybackService / ShowSessionService / ProjectService / SettingsService

### API

```text
EventBus.subscribe(event_type, handler)   # exact type; duplicate handler ignored
EventBus.unsubscribe(event_type, handler) # no-op if missing
EventBus.publish(event)                   # sync; handlers in order; exact type only
```

### Adoption status

```text
[created] core.EventBus
[not wired] application services
[not wired] MainWindow / UI
[not wired] Web Remote
[forbidden] position / playing as bus events (clock rule)
```

---

## Sprint 3.5 — Architecture snapshot (done)

Docs-only checkpoint after Sprint 3 Task 3. **No runtime code changes.**

Canonical snapshot: [`architecture_overview.md`](architecture_overview.md)

Includes: layer diagram, dependency graph, service / repository / protocol maps,
EventBus as-built + planned taxonomy, MainWindow responsibilities, debt map,
migration progress (Sprint 0→3), Sprint 4 roadmap, Feature Sprint candidates,
architecture decisions log.

---

## Sprint 4 — Feature Planning (done)

Docs-only. Canonical plan: [`roadmap.md`](roadmap.md).

**Recommended Feature:** Song Variants (select one), then Align/compare.

---

## Sprint 4 — Feature Task 1: Song Variant design (done)

Docs-only. Canonical design: [`song_variant_design.md`](song_variant_design.md).

- Audited Song / `AudioTrack` / schema v1
- Identified single-main-file call-site assumptions
- Proposed `SongVariant` + schema v2 migrate + compat mirror of `audio_tracks`
- **No production code**

---
## 1. Current folder structure

```text
CuePlayer_didido/
├── AGENTS.md / README.md / CHANGELOG.md / pyproject.toml
├── .ai/                    # AI workflow: NEXT_TASK, REPORT, handoffs, prompts
├── .cursor/rules/          # auto-push, ai-workflow
├── docs/                   # architecture + product + distribution manuals
├── fixtures/               # MA2/MA3 golden XML, media, export fixtures
├── packaging/              # Windows PyInstaller / Inno (Windows-only builds)
├── scripts/
├── tests/                  # ~mirrors packages; ui tests dominate
└── src/cueplayer/          # ~107 .py packages (no empty timeline/ltc stubs)
    ├── app.py              # QApplication boot + MainWindow
    ├── __main__.py         # python -m cueplayer
    ├── domain/             # models, undo, cue id, columns, media_relink, song_session
    ├── application/        # ProjectService, PlaybackService, SettingsService, ShowSessionService
    ├── repository/         # ProjectRepository (file I/O façade)
    ├── core/               # In-process infrastructure (EventBus); no Qt / no clock
    ├── ports/              # Protocol interfaces only (canonical)
    ├── playback/           # AudioEngine (clock), video sync/mix, devices, NDI, MTC/MIDI
    ├── media/              # decode, caches, BPM, LTC detect, av_path_lock
    ├── persistence/        # JSON project, bundle, backup, media layout, audio prefs
    ├── exporters/          # ma2/, ma3/, plan, show_patch, XML helpers
    ├── ui/                 # ~53% LOC — MainWindow hub + widgets/dialogs
    ├── web_remote/         # HTTP/WS server, bridge, static app.js
    ├── timecode/           # SMPTE / LTC / MTC helpers
    ├── routing/            # channel matrix
    ├── util/               # frozen runtime, thread priority
    └── spikes/             # early experiments
```

### LOC by package (approx., `.py` only)

| Package | LOC | Notes |
|---------|----:|-------|
| `ui/` | ~23.6k | Dominant; god-object `main_window` |
| `playback/` | ~5.8k | Clock + video audio + devices |
| `media/` | ~3.5k | Decode / caches / BPM |
| `web_remote/` | ~3.3k | Plus `static/app.js` ~3316 lines |
| `exporters/` | ~2.4k | Cleanest layer |
| `domain/` | ~2.2k | |
| `persistence/` | ~2.2k | |
| `timecode/` / others | small | |
| `ports/` | 0 → Protocols only | **Canonical** on tip after Task 2 |
| ~~`timeline/` / `ltc/`~~ | removed | Empty stubs deleted Task 2 |

---

## 2. Main entry points

| Entry | Path | Behavior |
|-------|------|----------|
| Module | `python -m cueplayer` → `__main__.py` | Calls `app.main()` |
| Package | `cueplayer.app:main` | Boot log, Qt app, splash, `MainWindow` |
| CLI side door | `cueplayer --bpm-detect …` | Headless BPM worker **before** full UI boot |
| Frozen EXE | Same `app.main` via packaging | Windows employee builds only |

Boot sequence (simplified):

```text
__main__ → app.main()
  ├─ [--bpm-detect] → media.bpm_analyzer.run_bpm_detect_cli → exit
  └─ QApplication + splash
        └─ MainWindow()          # composition root of nearly everything
              ├─ Project / Song
              ├─ AudioEngine
              ├─ VideoSyncController
              ├─ Timeline / Monitor / Transport / Setlist …
              └─ optional Web Remote bridge
```

There is **no** separate `application/` package yet. Composition and use-cases live inside `MainWindow`.

---

## 3. Major modules and their responsibilities

| Module | Intended job | As-built reality |
|--------|--------------|------------------|
| **domain** | Pure Project/Song/Mark rules | Mostly correct; `media_relink` reaches into media + persistence |
| **playback** | Sole sample clock + device I/O + TC outs + video audio mix | `AudioEngine` is wide; `clock.py` is a legacy wall-clock stub, not the master clock |
| **media** | Decode, waveform/PCM caches, BPM, LTC detect, PyAV lock | Clear; `av_path_lock` is a cross-cutting runtime contract |
| **persistence** | UTF-8 JSON + migrations + bundle/backup | Functional; still depends on exporters naming + (lazy) playback device default |
| **exporters** | Song → MA2/MA3 | Clean; UI constructs exporters directly |
| **ui** | Widgets | Also project lifecycle, media jobs, remote host adapter, autosave orchestration |
| **web_remote** | LAN control | Server/state unchanged; `bridge` talks only through `RemoteHost` (+ adapter) |
| **core** | Shared in-process infra | ✅ `EventBus` (not yet wired to services/UI) |
| **timecode / routing / util** | Helpers | Small and coherent |
| **ports** | Protocol seams | ✅ Present; ShowHost + RemoteHost adopted; others still mostly unwired |
| ~~**timeline/ / ltc/**~~ | — | Removed empty stubs (Task 2) |
### Runtime composition (as wired today)

```mermaid
flowchart TB
  MW[MainWindow]
  AE[AudioEngine<br/>sample clock]
  VS[VideoSyncController]
  TL[TimelineWidget]
  CM[CueMonitorPanel]
  TBAR[TransportBar]
  PS[persistence.project_store]
  WR[WebRemoteBridge]
  PREV[Preview / Clean / NDI]

  MW --> AE
  MW --> VS
  MW --> TL
  MW --> CM
  MW --> TBAR
  MW --> PS
  MW --> WR
  AE -->|position / playing| VS
  AE -->|position / playing| TL
  AE -->|position / playing| CM
  AE -->|position / playing| TBAR
  VS -->|frames| PREV
  WR -.->|RemoteHost adapter| MW
  TBAR -->|play/pause/stop/seek| AE
  TL -->|seek / scrub| AE
```

---

## 4. Current dependency graph

Static first-party imports (package → package), measured on this tip:

```text
(root)/app     → ui, media, util
ui             → domain, exporters, media, persistence, playback, util, web_remote
web_remote     → domain, media, persistence, playback, timecode, ui, util
playback       → domain, media, routing, timecode, util
media          → domain, util
persistence    → domain, exporters, media, playback   (audio_prefs → devices default)
exporters      → domain
routing        → domain
domain         → media, persistence                   (media_relink only)
spikes         → routing
```

```mermaid
flowchart LR
  app --> ui
  ui --> domain
  ui --> playback
  ui --> media
  ui --> persistence
  ui --> exporters
  ui --> web_remote
  web_remote --> ui
  web_remote --> playback
  web_remote --> domain
  playback --> media
  playback --> domain
  persistence --> domain
  persistence --> exporters
  domain -.->|media_relink| media
  domain -.->|media_relink| persistence
  exporters --> domain
```

### Boundary status vs `BOUNDARY_RULES.md`

| Edge | Status on this tip |
|------|--------------------|
| `persistence → ui` | **Cleared** (Sprint 0): uses `domain.cue_list_columns` |
| `domain → media/persistence` | Still present via `domain.media_relink` |
| `web_remote → MainWindow` privates | **Cleared in bridge** (Task 2); confined to `MainWindowRemoteHost` adapter |
| `ports` package | ✅ Present — ShowHost + RemoteHost adopted; other ports still mostly unwired |
| `cue_list_columns` | ✅ Single path: `domain.cue_list_columns` (UI shim removed) |
Non-UI importers of `cueplayer.ui.*`: only `app` (boot) and `web_remote.dialog` (`ui.checkbox`).

---

## 5. Largest files (top 10 by size)

By **line count** (`.py` / notable JS). Byte size order is the same for the giants.

| # | Lines | Path |
|--:|------:|------|
| 1 | 7637 | `ui/main_window.py` |
| 2 | 4507 | `ui/timeline_widget.py` |
| 3 | 3316 | `web_remote/static/app.js` |
| 4 | 2688 | `ui/cue_monitor_panel.py` |
| 5 | 2146 | `playback/audio_engine.py` |
| 6 | 1338 | `web_remote/bridge.py` |
| 7 | 1323 | `ui/mark_manager_dialog.py` |
| 8 | 1080 | `domain/models.py` |
| 9 | 989 | `media/bpm_analyzer.py` |
| 10 | 870 | `persistence/project_store.py` |

Honorable mentions: `setlist_sheet_page.py` (~819), `show_patch_page.py` (~737), `transport_bar.py` (~734), `web_remote/state.py` (~780).

---

## 6. Which files contain business logic mixed with UI

Not every domain import in UI is a smell (binding models to widgets is normal). The problem is **orchestration / rules / side effects** living in widgets.

| File | Mixed responsibilities (examples) |
|------|-----------------------------------|
| **`ui/main_window.py`** | Open/save/autosave/bundle/relink; song activate + audio prefetch; BPM/LTC job scheduling; undo push; MA name sync; setlist renumber; Clean/NDI toggles; Web Remote host; dirty tracking |
| **`ui/timeline_widget.py`** | Paint + zoom/scroll + mark/clip edit gestures + scrub + waveform cache ownership + cue-id helpers |
| **`ui/cue_monitor_panel.py`** | Cue table UX + column prefs + NOW chrome + renumber menu wiring + note/id edits |
| **`ui/setlist_sheet_page.py`** | Sheet UX + mutates `song.ma_export_name` via exporter naming rules |
| **`ui/song_edit_dialog.py`** | Form UX + MA export name suggestion |
| **`ui/mark_manager_dialog.py`** | Lane CRUD UI + `sync_lane_cue_ids` |
| **`ui/show_patch_page.py`** | Export plan UI + MA sanitize |
| **`ui/missing_media_dialog.py`** | Relink UX over domain `media_relink` (acceptable thin; domain still impure) |
| **`web_remote/bridge.py`** | Remote command surface over `RemoteHost` (adapter holds MainWindow privates) |

Pure-ish UI (theme, checkbox, icon button, spinboxes, row_color) is comparatively clean.

---

## 7. Circular imports (if any)

### Package-level

No hard package cycles such as `playback ↔ ui`. Soft/forbidden-ish edges: `domain → media/persistence`, `web_remote → ui` (dialog only).

### Module-level

| Pair | Nature |
|------|--------|
| `domain.models` ↔ `domain.main_cue_id` | **Real soft cycle:** `main_cue_id` imports models; `Song` methods lazily import `main_cue_id` inside methods. Works at runtime; awkward for typing/tools. |
| `timecode` package `__init__` ↔ `timecode.ltc` / `mtc` | Benign re-export pattern (submodules import `smpte`, package imports submodules). |
| `playback.audio_engine` → `midi_cue_notes` | One-way only (false positive if treating attribute names as imports). |

**Verdict:** No import-time deadlock found in normal UI boot. The only worth-tracking cycle is **models ↔ main_cue_id**.

---

## 8. Global state usage

CuePlayer avoids classic process-wide singletons for `Project` / `Song`, but has several **process-scoped** stores:

| Mechanism | Where | Role |
|-----------|-------|------|
| **`av_path_lock` registry** | `media/av_lock.py` (`_locks` dict) | Per-resolved-path `RLock` for PyAV; shared by preview, scrub, waveform, mixer, stand-in |
| **QSettings (`CuePlayer`/`CuePlayer`)** | `SettingsService` (+ `audio_prefs`, `web_remote/prefs`, `color_presets`) | Machine-global prefs |
| **Disk audio cache** | `media/audio_disk_cache` (+ MainWindow in-memory maps) | Cross-song PCM/waveform reuse |
| **Thread pools / tokens** | `MainWindow` | Load/BPM/LTC generation counters (`_audio_load_token`, `_song_activate_gen`, …) |
| **Shared mutable `Song` / `Project`** | Engine, video_sync, timeline, monitor, remote | Not a Python `global`, but **shared object identity** is the real global state |

There is no DI container; `MainWindow` owns references.

---

## 9. Existing models

Primary home: `domain/models.py` (+ helpers in sibling modules).

| Type / area | Location | Notes |
|-------------|----------|-------|
| `Project` | `models.py` | Setlist, songs, categories, audio/clean/MA settings, UI chrome prefs persisted in JSON |
| `Song` | `models.py` | Timebase, audio tracks, video clips, mark lanes, LTC sides, BPM, setlist fields |
| `AudioTrack`, `VideoClip`, `Mark`, `MarkLane` | `models.py` | Core timeline entities |
| `SetlistCategory` | `models.py` | Folders |
| `MaExportSettings`, `AudioOutputSettings`, `CleanVideoOutputSettings` | `models.py` | Nested settings objects |
| Cue list column constants | `domain/cue_list_columns.py` | **Only** supported path (UI shim removed Task 2) |
| Cue ID rules | `domain/main_cue_id.py` | Assign/renumber/sort |
| Undo commands | `domain/undo.py` | Command objects over Project/Song |
| Relink scan helpers | `domain/media_relink.py` | Domain-named but reaches media/persistence |

Schema version constant lives with models (`SCHEMA_VERSION`); migrations live in
`persistence/project_migrations.py` (invoked by `load_project`, not Repository).

---

## 10. Existing services

| Service | Home | Notes |
|---------|------|-------|
| **`ProjectService`** | `application/project_service.py` | Lifecycle; I/O via `ProjectRepository` |
| **`PlaybackService`** | `application/playback_service.py` | ✅ Transport + volume/loop/scrub/nudge → AudioEngine |
| **`SettingsService`** | `application/settings_service.py` | ✅ Machine QSettings + audio_prefs façade |
| **`ShowSessionService`** | `application/show_session_service.py` | ✅ Activate/deactivate; host typed as `ShowHost` |
| **`ShowHost`** | `ports/show_host.py` | ✅ Explicit host Protocol for ShowSession |
| **`RemoteHost`** | `ports/remote_host.py` | ✅ Explicit host Protocol for Web Remote |
| **`MainWindowRemoteHost`** | `web_remote/main_window_remote_host.py` | ✅ Adapter (private access confined here) |
| **`SongSession`** | `domain/song_session.py` | ✅ Current song + transport snapshot (mirror) |
| Song activate orchestration | `ShowSessionService` | MainWindow thin wrapper; host owns loaders |
| Media job queue | `MainWindow` executors | Still UI-owned |
| Video output fan-out | `MainWindow` + `VideoSyncController` | Still UI-owned |
| Export orchestration | UI + `exporters/*` | |
| Remote command surface | `web_remote.bridge` | ✅ Talks only through `RemoteHost` |
| **`EventBus`** | `core/event_bus.py` | ✅ Infrastructure only — not adopted by services/UI yet |
| Playback clock / mix | `AudioEngine` | Unchanged internals |
| Frame clock follower | `VideoSyncController` | |

`MainWindow` still owns dialogs, media layout/bundle, song-activate refresh order, and applying a loaded `Project` to widgets.

---

## 11. Existing repositories

| Repository | Home | Notes |
|------------|------|-------|
| **`ProjectRepository`** | `repository/project_repository.py` | ✅ Task 4 — `load`/`save`/`autosave`/`backup`/`exists` |

Internally calls unchanged `persistence.project_store` + `persistence.backup`. No generic repository base class.

Other persistence remains function-oriented (`project_bundle`, `media_layout`, `audio_prefs`, …) until later tasks.

---

## 12. Current save/load flow

```mermaid
sequenceDiagram
  participant User
  participant MW as MainWindow
  participant Layout as media_layout / bundle
  participant Backup as backup
  participant Store as project_store
  participant Disk as UTF-8 JSON

  User->>MW: Open…
  MW->>Store: load_project(path)
  Store->>Disk: read + migrate + project_from_dict
  Store-->>MW: Project
  MW->>MW: engine.stop / _apply_project / overlay global audio prefs

  User->>MW: Save / Autosave
  MW->>MW: pull Clean + decode quality into Project
  MW->>Layout: optional bundle + Media/ sync
  MW->>Backup: create_backup_before_save
  MW->>Store: save_project(project, path)
  Store->>Disk: project_to_dict + json.dumps(ensure_ascii=False)
  MW->>MW: _set_clean()
```

Notes:

- Dirty flag `_dirty` is owned by `MainWindow` (not domain).
- Autosave: QTimer + QSettings interval; quiet `_file_save`.
- Load path also used by “Collect Bundle” then reopen bundled JSON.
- Missing media: after open, relink dialog via `domain.media_relink.scan_missing_media`.
- Machine audio prefs from QSettings **overlay** project JSON on apply (`apply_global_audio_to_project`).

---

## 13. Current playback flow

```mermaid
flowchart LR
  subgraph inputs
    Transport
    Timeline
    Space[Space shortcut]
    Remote[Web Remote]
  end

  subgraph clock
    AE[AudioEngine]
  end

  subgraph followers
    VS[VideoSyncController]
    TL[TimelineWidget]
    Mon[CueMonitorPanel]
    OutTC[Output TC clock UI]
  end

  subgraph frames
    Prev[Video Preview]
    Clean[Clean Output]
    NDI[NDI]
  end

  Transport -->|play/pause/stop/seek/volume| AE
  Timeline -->|seek/scrub| AE
  Space --> AE
  Remote -->|RemoteHost adapter| AE
  AE -->|position_changed / playing_changed| VS
  AE --> TL
  AE --> Mon
  AE --> OutTC
  VS --> Prev
  VS --> Clean
  VS --> NDI
```

Rules in force:

- **`AudioEngine.position` (sample-based) is the only playback clock.**
- Video windows share one decode path through `VideoSyncController` (not a second player).
- Song switch: `quiesce_output` → swap `current_song` → `set_song` on timeline/monitor/sync/engine → async audio load under `av_path_lock` discipline.
- Embedded video audio mixes in `VideoAudioMixer` inside/ beside the engine path.
- Web Remote reaches the clock only via `RemoteHost` / `RemoteEnginePort` (not MainWindow privates).

---

## 14. Current settings flow

Settings are split across **machine** vs **project** stores:

```text
┌─────────────────────────────┐
│ Project JSON (per show)     │  marks, songs, MA export, clean geometry,
│ persistence.project_store   │  decode quality, many chrome flags, etc.
└─────────────┬───────────────┘
              │ load overlays ↓
┌─────────────▼───────────────┐
│ SettingsService             │
│ → QSettings CuePlayer/…     │
│ • audio/output_settings_json│  ← audio_prefs (wins over project on apply)
│ • autosave/*                │  ← machine prefs (also used by ProjectService)
│ • UI session / monitor cols │  ← MainWindow via SettingsService
│ (not yet): web remote,      │  ← still web_remote.prefs / color_presets
│            color presets    │
└─────────────────────────────┘
              │
┌─────────────▼───────────────┐
│ Live widgets                 │
│ Audio Timecode dialog,       │
│ Transport, Clean window, …   │
│ mutate Project and/or machine│
│ prefs via SettingsService    │
└─────────────────────────────┘
```

Machine State and Project State must remain separate — SettingsService never owns Project JSON.

---

## 15. Technical debt (prioritized)

### Cleared in Sprint 1 Task 2

- Split tip / missing `ports/` sources  
- `ui.cue_list_columns` shim + dual import paths  
- Empty `timeline/` / `ltc/` stubs  
- Dead `playback.clock.PlaybackClock` wall-clock  
- Unused `_AUDIO_SUFFIXES` re-export alias on `MainWindow`

### Cleared in Sprint 3 Task 2

- `web_remote.bridge` duck-typing MainWindow / engine privates

### Cleared in Sprint 3 Task 3

- Missing in-process EventBus primitive (now `core.EventBus`; not yet adopted)

### P0 — Next (Song Variant implementation)

1. **Song Variants domain + schema v2** — see `docs/song_variant_design.md`.
2. Retarget main-audio path helpers to `selected_audio_path` (one buffer).
3. Architecture spine (parallel/backlog): Playback events on EventBus (no playhead ticks).
4. Optional: ShowHost/RemoteHost façades; Settings fold-in.

### P1 — Structural risk (product-visible)

4. **`MainWindow` god-object (~7.6k)** — composition + use-cases.
5. **Shared mutable `Song`** — missed refresh → A/V or list desync.
6. **`av_path_lock` contention** — preview/scrub/waveform/mixer share path locks.
7. **`AudioEngine` breadth** — device + routing + LTC/MTC/MIDI + video audio in one type.

### P2 — Layering / maintainability

8. **`domain.media_relink` → media/persistence** — violates target domain purity.
9. **`persistence` → `exporters.common` naming** — storage coupled to MA sanitize rules.
10. **`models` ↔ `main_cue_id` soft cycle**.
11. **Giant UI files** (`timeline_widget`, `cue_monitor_panel`).
12. **No repository classes** (intentional until a later sprint; functions in `persistence/` are fine).
13. **RemoteHost adapter still wraps engine/mixer privates** for video listen.

### P3 — Deferred

14. Full `adapters/` tree rename of playback/media.
15. Rewriting `AudioEngine` / timeline paint architecture.
16. Product features under an “architecture” banner.

---

## Documentation merge / simplify notes

Sprint 1 should **not** delete history blindly, but can reduce agent confusion:

| Action | Recommendation |
|--------|----------------|
| Keep **this file** | Sprint 1 baseline “what is true on trunk after unify” |
| Banner on `ARCHITECTURE_REVIEW.md` | “Superseded for English baseline by `current_architecture.md`; ZH narrative retained” |
| Slim `ARCHITECTURE.md` | Point to current + target + boundary; drop duplicated long prose |
| Do **not** merge BOUNDARY/MIGRATION into review docs | Law docs should stay short and permanent |
| Fix `PRODUCT_SPEC` status header | Separate tiny docs chore |

---

# Sprint plan status

| Task | Status | Notes |
|------|--------|-------|
| Sprint 1 · 1–4 | ✅ Done | Assessment → cleanup → ProjectService → ProjectRepository |
| Sprint 2 · 5–8 | ✅ Done | Playback → boundary → Settings → ShowSession |
| Sprint 3 · 1 | ✅ Done | Explicit `ports.ShowHost` |
| Sprint 3 · 2 | ✅ Done | `RemoteHost` + `MainWindowRemoteHost`; bridge clean |
| **Sprint 3 · 3** Event Bus foundation | ✅ Done | `core.EventBus` (subscribe/unsubscribe/publish); no adopters yet |
| **Sprint 3.5** Architecture snapshot | ✅ Done | `docs/architecture_overview.md` (docs only) |
| **Sprint 4 Planning** Feature plan | ✅ Done | `docs/roadmap.md` |
| **Sprint 4 · F1** Song Variant design | ✅ Done | `docs/song_variant_design.md` |
| **Sprint 4 · F2** Song Variant domain | ✅ Done | `domain/song_variant.py` + tests |
| **Sprint 4 · F3** Song Variant persistence | ✅ Done | schema v2 + `project_migrations` |
| **Next** Playback variant support | **Queued** | Retarget load to `selected_audio_path` |
| Sprint 4 arch spine · Playback events | Backlog | First EventBus adoption (not the Feature pick) |

### After Feature Task 3

Wire playback load paths to `song.selected_audio_path()` (one buffer).  
Do **not** auto-start until the user continues.

---

## READY FOR PLAYBACK VARIANT SUPPORT
