# CuePlayer Boundary Rules

**Status:** Permanent architecture rule  
**Audience:** Humans + Cursor / ChatGPT agents  
**Related:** [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md) · [`ARCHITECTURE_REVIEW.md`](ARCHITECTURE_REVIEW.md) · [`MIGRATION_RULES.md`](MIGRATION_RULES.md) · [`../.ai/WORKFLOW.md`](../.ai/WORKFLOW.md)

These rules define **who may depend on whom**. Violating them recreates the
as-built problems in `ARCHITECTURE_REVIEW.md` (UI hub, persistence→UI leak,
Remote touching MainWindow privates, domain pulling media).

---

## 1. Layer map (target)

```text
app / ui                    # widgets + composition shell
    ↓
application                 # use-cases / session orchestration (future)
    ↓
ports                       # Protocol interfaces only (step 0 done)
    ↑
adapters                    # playback, media, persistence, exporters,
                            # timecode, routing, remote (future layout)
    ↓
domain                      # Project / Song / Mark / undo / pure helpers
```

**Clock non-negotiable:** `PlaybackClock` / today’s `AudioEngine` sample
position is the **only** playback clock. Video Preview / Clean / NDI / Remote
preview are **frame sinks** on one decode path — never a second player clock
(`AGENTS.md`).

---

## 2. Module boundaries

| Module | Responsibility | May depend on | Must not depend on |
|--------|----------------|---------------|--------------------|
| **domain** | Pure model + domain rules (marks, cue ids, undo commands) | stdlib, typing | `ui`, `playback`, `media`, `persistence`, `exporters`, `web_remote`, `application` |
| **ports** | Protocol seams only | `domain` (types in signatures), typing | `ui`, `playback`, `media`, `persistence`, `exporters`, `web_remote`, `application`, adapters |
| **application** | Use-cases (save, song session, export orchestration) | `domain`, `ports` | `ui` widgets, concrete PortAudio/PyAV, MainWindow privates |
| **adapters.playback** | AudioEngine, video sync/mix, devices, NDI, MTC/MIDI | `domain`, `ports`, `media`, `timecode`, `routing` | `ui`, `web_remote` |
| **adapters.media** | Decode, caches, BPM, `av_path_lock` | `domain` (minimal), stdlib/native libs | `ui`, `application` |
| **adapters.persistence** | JSON load/save, bundle, backup, media layout | `domain`, `ports` (optional) | **`ui`** (forbidden), Qt widgets |
| **adapters.exporters** | MA2/MA3 XML / Plugin / Macro | `domain` | `ui`, `playback`, `web_remote` |
| **adapters.remote** | Web Remote server/bridge/static | `domain`, `ports` (`RemoteHost`, `PlaybackClock`) | MainWindow private `_` APIs; deep UI widgets except shared chrome if unavoidable |
| **ui** | Widgets, dialogs, painting | `domain`, `application`, `ports`, adapters (transitional) | Becoming the permanent home of business orchestration |
| **app** | Process entry / composition root | `ui`, `application`, adapters | Domain logic inline |

Today many adapters still live at top-level (`cueplayer.playback`, `.media`,
…). Treat those paths as **current adapter homes** until migration moves them
under `adapters/`. The **dependency directions** above still apply.

---

## 3. Allowed dependency directions

```text
ui              →  application | domain | ports | adapters*   (transitional: ui→adapters OK)
application     →  domain | ports
adapters.*      →  domain | ports | (other adapters only when unavoidable & documented)
ports           →  domain (types only)
domain          →  (nothing inside cueplayer except other domain modules)
```

\*Transitional: until application services exist, `ui` may call adapters
directly (as `MainWindow` does today). New code should prefer going through
`application` + `ports` when those modules exist for that use-case.

### Product / runtime edges that stay intentional

- **playback → media** — engine/mixer needs decoders & PCM (allowed).
- **playback → timecode / routing** — LTC/MTC & channel matrix (allowed).
- **ui → playback** — composition root wiring the clock (allowed until shell thins).
- **exporters → domain** — plans from `Song` (allowed; keep exporters free of ui/playback).

---

## 4. Forbidden dependency directions

| Forbidden edge | Why |
|----------------|-----|
| **persistence → ui** | Storage must not know Qt column widgets / UI packages. Breaks headless load and creates import cycles. |
| **domain → media / persistence / playback** | Domain stops being a pure leaf; tests and exporters get dragged into I/O. |
| **ports → adapters / ui** | Interfaces must not depend on implementations. |
| **exporters → ui / playback / web_remote** | MA XML must stay deterministic and fixture-testable. |
| **remote → MainWindow private `_…` APIs** | Rename/refactor of UI internals breaks LAN control. Use `ports.RemoteHost`. |
| **media → ui** | Decoders must not import widgets. |
| **Any module → second playback clock** | Violates sample-clock master rule; desyncs video/audio/marks. |

Known as-built violations to **eliminate on their migration step** (do not add new ones):

- `persistence.project_store` → `ui.cue_list_columns` → fixed at **step 1**
- `domain.media_relink` → media/persistence → clean when that helper is relocated
- `web_remote` duck-typing MainWindow privates → fixed at **RemoteHost step**

---

## 5. Import examples

### Allowed

```python
# ports may use domain types in signatures
from cueplayer.domain.models import Song
from typing import Protocol

class PlaybackClock(Protocol):
    def set_song(self, song: Song | None) -> None: ...


# adapters.playback may use media
from cueplayer.media.video_audio_cache import get_video_audio


# exporters may use domain only
from cueplayer.domain.models import Song
from cueplayer.exporters.plan_from_song import build_export_plan


# ui composition may construct the clock (transitional)
from cueplayer.playback.audio_engine import AudioEngine
```

### Forbidden

```python
# persistence must not import ui
from cueplayer.ui.cue_list_columns import normalize_cue_list_column_order  # NO


# domain must not open media caches
from cueplayer.media.audio_disk_cache import adopt_caches_for_path  # NO (in domain)


# ports must not import playback
from cueplayer.playback.audio_engine import AudioEngine  # NO


# remote must not reach into MainWindow privates
host._video_standin_cache  # NO
host._push_song_undo(...)  # NO — go through RemoteHost


# exporters must not import ui
from cueplayer.ui.main_window import MainWindow  # NO
```

---

## 6. Shared runtime resources (not import edges, still boundaries)

These are **execution** hazards; treat them as part of the architecture fence:

| Resource | Rule |
|----------|------|
| **`av_path_lock`** | All PyAV path access shares the per-path lock. New consumers must document contention with Preview / mixer / scrub / waveforms. |
| **Shared mutable `Song`** | engine / video_sync / timeline / monitor / remote alias one object. After mutation, refresh via `SongSession` (port) — do not leave a surface stale. |
| **Frame fan-out** | One decode path → many `FrameSink`s. Do not invent a parallel decoder for NDI/Clean/Remote. |

---

## 7. How agents must use this doc

1. Before any migration or new feature that crosses packages, re-read this file.
2. If a change would add a **forbidden** edge, stop and redesign (or schedule the migration step that removes the need).
3. Temporary violations are only allowed when `ARCHITECTURE_TARGET` explicitly says that step will clear them — and the PR must not add *new* violations elsewhere.
4. Pair with [`MIGRATION_RULES.md`](MIGRATION_RULES.md) for *how* to move code without breaking behavior.
