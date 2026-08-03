# CuePlayer — Architecture Overview (Sprint 3.5 Snapshot)

**Status:** Sprint 3.5 complete (documentation snapshot only)  
**Updated:** 2026-08-03  
**Scope tip:** `cursor/sprint35-architecture-snapshot-028d`  
**Constraint:** Docs only — no runtime code changes in this task.

Related:

| Doc | Role |
|-----|------|
| [`current_architecture.md`](current_architecture.md) | Living as-built assessment + sprint notes |
| [`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md) | Strangler target layout |
| [`BOUNDARY_RULES.md`](BOUNDARY_RULES.md) / [`MIGRATION_RULES.md`](MIGRATION_RULES.md) | Permanent law |
| [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md) | Product requirements |
| **This file** | Concise Sprint 0→3 architecture snapshot for planning |

---

## 1. Current architecture

### Layer diagram

```text
┌─────────────────────────────────────────────────────────────┐
│ app.py / __main__          composition root (boot + splash) │
└───────────────────────────────┬─────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────┐
│ ui/  (MainWindow shell + widgets)                           │
│   timeline · monitor · transport · setlist · dialogs · …    │
└───────┬─────────────────────────────┬───────────────────────┘
        │                             │
        ▼                             ▼
┌───────────────────┐     ┌───────────────────────────────────┐
│ application/      │     │ web_remote/                       │
│ ProjectService    │     │ Bridge ──RemoteHost──► adapter    │
│ PlaybackService   │     │ Server / WebRTC / static (unch.)  │
│ SettingsService   │     └───────────────────────────────────┘
│ ShowSessionService│
└─────────┬─────────┘
          │
          ├──────────────► ports/   (Protocols; ShowHost + RemoteHost adopted)
          ├──────────────► repository/ ProjectRepository
          ├──────────────► domain/  Project · Song · Marks · SongSession · undo
          └──────────────► core/    EventBus ⚠ not wired yet
                                │
                ┌───────────────┼────────────────┐
                ▼               ▼                ▼
         playback/         media/          persistence/
         AudioEngine       decode/BPM      JSON / bundle /
         (sole clock)      LTC detect      backup / prefs
         video sync/mix    av_path_lock
                │
                ▼
         exporters/ · timecode/ · routing/
```

**Clock rule (non-negotiable):** `AudioEngine` sample position is the only playback clock. Preview / Clean / NDI / Remote preview are frame sinks on one decode path — never a second player.

### Dependency graph (first-party packages)

```text
ui            → application, domain, exporters, media, persistence, playback, util, web_remote
application   → domain, media*, persistence*, playback*, ports, repository
repository    → domain, persistence
ports         → domain (types only)
core          → (none)
domain        → media*, persistence*   ← debt via media_relink
web_remote    → domain, media, persistence, playback, ports, timecode, ui*, util
playback      → domain, media, routing, timecode, util
media         → domain, util
persistence   → domain, exporters*, media*, playback*
exporters     → domain
routing       → domain
timecode / util / core → leaf
```

\*Transitional or known-debt edges. `web_remote → ui` is dialog checkbox only; bridge no longer duck-types MainWindow privates.

### Service map

| Service | Home | Owns | Does not own |
|---------|------|------|--------------|
| **ProjectService** | `application/project_service.py` | New/open/save, dirty, recent/autosave orchestration | Dialogs, media layout/bundle, widget apply |
| **ProjectRepository** | `repository/project_repository.py` | `load`/`save`/`autosave`/`backup`/`exists` | Schema redesign |
| **PlaybackService** | `application/playback_service.py` | Transport, volume/mute/gain, A–B loop, scrub, nudge | Song activate orchestration, device open |
| **SongSession** | `domain/song_session.py` | Current song + playing/position/duration mirror | UI widgets |
| **SettingsService** | `application/settings_service.py` | Machine QSettings + audio prefs façade | Project JSON |
| **ShowSessionService** | `application/show_session_service.py` | Activate/deactivate coordination | Media loader implementations |
| **WebRemoteBridge** | `web_remote/bridge.py` | HTTP/WebRTC marshal → `RemoteHost` | Networking redesign |

### Repository map

| Repository | Methods | Backing |
|------------|---------|---------|
| **ProjectRepository** | `load`, `save`, `autosave`, `backup`, `exists` | `persistence.project_store` + `persistence.backup` |

Other persistence remains function-oriented (`project_bundle`, `media_layout`, `audio_prefs`, `web_remote.prefs`, `color_presets`).

### Protocol map

| Protocol | File | Adoption |
|----------|------|----------|
| **ShowHost** (+ nested engine/timeline/monitor/video/transport/status) | `ports/show_host.py` | ✅ ShowSessionService |
| **RemoteHost** / **RemoteEnginePort** | `ports/remote_host.py` | ✅ WebRemoteBridge via MainWindowRemoteHost |
| **PlaybackClock** | `ports/clock.py` | Structural (AudioEngine); not fully wired as DI |
| **SongSession** (port) | `ports/song_session.py` | Domain class exists; port lightly used |
| **ProjectStore** | `ports/project_store.py` | Repository wraps persistence functions instead |
| **AudioDevicePort** | `ports/audio_device.py` | Defined; not strangler-wired |
| **VideoDecoderPort** / **VideoAudioSource** / **FrameSink** | ports | Defined; not strangler-wired |
| **ShowExporter** | `ports/exporter.py` | Defined; UI still constructs exporters |
| **MediaJobQueue** | `ports/media_jobs.py` | Defined; jobs still MainWindow-owned |

### Current EventBus architecture

```text
cueplayer.core.EventBus
  subscribe(event_type, handler)   # exact type; dup ignored
  unsubscribe(event_type, handler) # no-op if missing
  publish(event)                   # sync; order preserved; exact type only

Adopters:  NONE (infrastructure only — Sprint 3 Task 3)
Forbidden: continuous playhead / sample-position events (clock rule)
Not yet:   async, sticky, replay, priorities, threading, networking
```

Qt signals remain the local widget wiring mechanism. EventBus is a future fan-out seam for services → chrome / observers.

### Planned event taxonomy (not implemented)

| Tier | Candidate events | Notes |
|------|------------------|-------|
| **P0 Playback chrome** | `PlayingChanged`, `SongBound` / `SongActivated`, `LoopChanged`, `MusicMuteChanged` | Discrete state changes only |
| **P1 Session / project** | `ProjectDirtyChanged`, `MarksChanged`, `SetlistChanged` | After playback adoption |
| **P2 Remote observers** | Same discrete events consumed by RemoteHost adapters | Do not duplicate clock |
| **Forbidden** | Per-frame / per-sample position ticks | Stay on AudioEngine signals |

Start with **2–4** playback events in the first adoption task.

### MainWindow responsibilities (as-built)

`ui/main_window.py` remains the composition root (~7.4k+ lines).

| Owns today | Delegated |
|------------|-----------|
| Widget tree + layout/session geometry | Playback transport/volume/loop/scrub → PlaybackService |
| Dialogs, menus, undo stack push sites | Project I/O dirty/path → ProjectService → Repository |
| Media warm / BPM / LTC detect job tokens | Machine prefs → SettingsService |
| Audio load caches / stand-in / waveform apply | Song activate order → ShowSessionService |
| Video preview / Clean / NDI fan-out wiring | Remote ops → RemoteHost adapter |
| Mark editing helpers still private | — |
| Implements ShowHost structurally | — |

Public surface is thin; most behavior is private `_` helpers (~270+).

---

## 2. Remaining architectural risks

| Risk | Why it matters | Mitigation direction |
|------|----------------|----------------------|
| **MainWindow god-object** | Hard to test; every feature touches the hub | Continue strangler: services + EventBus adopters |
| **Shared mutable Song** | Missed refresh → A/V or cue-list desync | Discrete MarksChanged / SongBound events |
| **av_path_lock contention** | Preview/scrub/waveform/mixer share path locks | Keep lock discipline; avoid second decoder |
| **AudioEngine breadth** | Device + routing + TC + video audio in one type | Ports exist; extract only with behavior tests |
| **EventBus misuse as clock** | Desyncs video/marks/remote | Hard rule: no position ticks on bus |
| **domain.media_relink → media/persistence** | Domain purity leak | Relocate helper when touching relink |
| **Remote adapter privates** | Engine mixer still reached via `_` in adapter | Public listen façade later |
| **ShowHost `_` helper names** | Protocol documents UI privates | Lift to public host façades |
| **Giant UI files** | timeline / cue_monitor hard to change safely | Split only with paint/interaction tests |

---

## 3. Recommended Sprint 4 roadmap

Architecture spine continues, interleaved with product polish — not a rewrite.

| Step | Focus | Constraint |
|------|-------|------------|
| **4.1** | Playback events on EventBus (2–4 discrete events) | No playhead ticks; optional one UI subscriber |
| **4.2** | Optional: route remote transport/loop via PlaybackService | Preserve RemoteHost boundary |
| **4.3** | Optional: ShowHost / RemoteHost public façades for hottest `_` helpers | No MainWindow redesign |
| **4.4** | Optional: SettingsService fold-in (`web_remote.prefs`, color presets) | Machine vs project split stays |

Do **not** start `adapters/` tree rename or AudioEngine rewrite in Sprint 4.

---

## 4. Recommended Feature Sprint candidates

Product-facing work that fits after the architecture snapshot (cue accuracy first; NDI last among video outs).

| Candidate | Why now | Depends on |
|-----------|---------|------------|
| **Video / alignment UX polish** | Timeline + marks already solid; alignment is daily workflow | Existing sample-locked video |
| **Setlist / timeline / export selection row colors** | Explicitly deferred; low architecture risk | UI chrome only |
| **Cue list / NOW display polish** | Operator-facing; columns/IDs already shipped | Monitor widgets |
| **BPM / LTC detect UX hardening** | Jobs still MainWindow-owned; UX > relocate | Existing media jobs |
| **MA export / Show Patch polish** | Exporters already cleanest layer | Fixtures |
| **NDI polish** | Only after cue accuracy remains solid | VideoSync / frame sinks |
| **Web Remote UX polish** | Boundary now explicit; safe to improve static app | RemoteHost |

Avoid bundling Feature Sprint work with EventBus clock semantics or AudioEngine redesign.

---

## 5. Architecture decisions made so far

| Decision | Sprint | Rationale |
|----------|--------|-----------|
| Strangler Fig; one module per task | 0 / permanent | No big-bang rewrite |
| `ports/` Protocols before moving packages | 0 | Fix dependency direction first |
| `cue_list_columns` → domain only | 0–1 | Kill persistence→ui leak |
| Application services for lifecycle / playback / settings / session | 1–2 | Thin MainWindow without relocating adapters |
| Repository wraps existing persistence | 1 | No persistence redesign |
| PlaybackService owns transport + volume/loop/scrub/nudge | 2 | UI must not write engine gains/loops directly |
| SongSession is transport read-model mirror | 2 | Not a second clock |
| SettingsService = machine prefs only | 2 | Never Project JSON in QSettings |
| ShowSessionService orchestrates activate | 2 | MainWindow keeps loaders |
| Explicit ShowHost Protocol | 3.1 | End duck-typed `Any` host |
| Explicit RemoteHost + adapter | 3.2 | Bridge never touches MainWindow `_` |
| EventBus sync, type-keyed, no adopters yet | 3.3 | Infra before migration |
| AudioEngine remains sole sample clock | permanent | AGENTS.md / BOUNDARY_RULES |
| Unicode paths / Display vs MA Export Name split | permanent | Product non-negotiables |

---

## 6. Migration progress (Sprint 0 → Sprint 3)

```text
Sprint 0  ✅  AI workflow, BOUNDARY/MIGRATION law, ports package, columns domain move
Sprint 1  ✅  Assessment → transitional cleanup → ProjectService → ProjectRepository
Sprint 2  ✅  Playback foundation → Playback boundary → SettingsService → ShowSessionService
Sprint 3  ✅  ShowHost Protocol → RemoteHost boundary → EventBus foundation
Sprint 3.5 ✅ Architecture snapshot (this document)
──────────
Next      → Feature Sprint Planning (product candidates + Sprint 4 arch spine)
Queued    → Playback events (first EventBus adoption; still recommended early in Sprint 4)
```

| Layer | Progress |
|-------|----------|
| Ports defined | ✅ |
| Ports adopted (ShowHost, RemoteHost) | ✅ partial |
| Application services | ✅ 4 services |
| Repository | ✅ Project only |
| EventBus | ✅ created / ❌ unwired |
| adapters/ rename | ❌ deferred |
| MainWindow thin shell | 🟡 in progress |
| domain purity | 🟡 media_relink debt remains |

---

## 7. Technical debt map (condensed)

| Priority | Item |
|----------|------|
| **P0** | Adopt EventBus for discrete playback chrome (not clock) |
| **P0** | Keep RemoteHost / ShowHost from regressing to duck-typing |
| **P1** | MainWindow size; shared Song refresh; av_path_lock; AudioEngine breadth |
| **P2** | media_relink purity; persistence→exporters naming; models↔cue_id cycle; giant UI files; Remote listen privates in adapter |
| **P3** | adapters/ tree rename; engine/timeline rewrite; feature work labeled as “architecture” |

---

## READY FOR FEATURE SPRINT PLANNING
