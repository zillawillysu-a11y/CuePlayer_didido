# CuePlayer — Product & Architecture Roadmap

**Status:** Sprint 5 Align Anchors Beta complete — production-ready  
**Updated:** 2026-08-03  
**Scope tip:** `cursor/sprint5-align-beta-028d`
**Related:** [`song_variant_design.md`](song_variant_design.md) · [`architecture_overview.md`](architecture_overview.md) · [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md) · [`current_architecture.md`](current_architecture.md) · [`AGENTS.md`](../AGENTS.md)

---

## Planning principles

Prioritize by:

1. **Daily workflow improvement** — programming / show-prep hours saved every day  
2. **Production reliability** — cue accuracy, clock integrity, export safety  
3. **Long-term maintainability** — fits strangler seams; no god-object growth  

**Exclude from Feature Sprints:** large rewrites, plugin systems, major UI redesigns, architecture-only tasks (EventBus adoption stays on the Sprint 4 *architecture spine*, not as the Feature pick).

**Hard product rules still apply:** sole `AudioEngine` clock; Unicode paths; Display Name ≠ MA Export Name; no Chinese in MA XML labels.

---

## Top 10 Feature candidates

Sprint size key: **S** ≈ 1 focused task · **M** ≈ 2–4 tasks · **L** ≈ full Feature Sprint · **XL** = split before starting.

### 1. Multi-audio / Song Variants + Align Anchors — **Sprint 4 Feature**

| | |
|--|--|
| **User value** | Multiple media mixes per song; cues stay on the song; switch playback bed without rebuilding marks. |
| **Technical complexity** | **M–L** — design: [`song_variant_design.md`](song_variant_design.md); domain already has `AudioTrack` but runtime is replace-only main. |
| **Dependencies** | Persistence migration v2; retarget main-path helpers; ShowSession load path. |
| **Architectural impact** | Medium (domain + schema); clock stays one buffer. |
| **Risks** | Dual `audio_tracks`/`variants` drift; duration/LTC on switch; scope creep into simultaneous compare. |
| **Sprint size** | **L** — implement variants (select one) first; Align Anchors / compare later |
| **Design status** | ✅ Task 1 design complete → **READY FOR SONG VARIANT IMPLEMENTATION** |

### 2. Video ↔ music alignment UX polish

| | |
|--|--|
| **User value** | Faster clip nudge / hide Video+LTC after align / sync-calib clarity — daily VJ programming. |
| **Technical complexity** | **S–M** — behavior mostly exists; polish gestures, affordances, defaults. |
| **Dependencies** | Sample-locked video clips, VideoSync, timeline. |
| **Architectural impact** | Low — UI/timeline only; keep single decode path. |
| **Risks** | Accidental second decoder; playhead jank if paint work grows. |
| **Sprint size** | **M** |

### 3. Selection / sheet row-color consistency

| | |
|--|--|
| **User value** | Colored setlist songs readable in Sheet + selection chrome (explicitly deferred). |
| **Technical complexity** | **S** — `row_color` + `RowColorDelegate` exist; Sheet/timeline/export selection gaps. |
| **Dependencies** | `ui/row_color.py`, color presets. |
| **Architectural impact** | Very low. |
| **Risks** | Theme contrast / accessibility; selection overlay fights accent. |
| **Sprint size** | **S–M** |

### 4. MA Export Preview / editable name check

| | |
|--|--|
| **User value** | See MA labels before XML; fix pinyin/illegal chars without round-tripping console — production safety. |
| **Technical complexity** | **M** — exporters clean; need preview UI over existing sanitize/plan. |
| **Dependencies** | `exporters/*`, Show Patch, Display vs MA name split. |
| **Architectural impact** | Low — prefer thin application helper over MainWindow logic. |
| **Risks** | Preview drift from real export; Chinese-in-label regressions. |
| **Sprint size** | **M** |

### 5. Cue list / NOW display polish

| | |
|--|--|
| **User value** | Operator glanceability during programming (columns, follow, cue id). |
| **Technical complexity** | **S–M** — columns/IDs largely shipped. |
| **Dependencies** | Cue monitor, domain cue-id rules. |
| **Architectural impact** | Low. |
| **Risks** | Layout thrash; playhead-follow jank. |
| **Sprint size** | **S–M** |

### 6. BPM / LTC detect UX hardening

| | |
|--|--|
| **User value** | Clearer progress/errors for detect jobs; fewer “stuck badge” moments. |
| **Technical complexity** | **M** — jobs still MainWindow-owned. |
| **Dependencies** | media BPM/LTC detect, setlist badges. |
| **Architectural impact** | Low if UX-only; medium if extracting MediaJobQueue port. |
| **Risks** | Touching async tokens without EventBus; false confidence in BPM. |
| **Sprint size** | **M** |

### 7. Web Remote UX polish (static app)

| | |
|--|--|
| **User value** | iPad programming comfort after RemoteHost boundary. |
| **Technical complexity** | **S–M** — JS/CSS + existing ops. |
| **Dependencies** | RemoteHost (done); do not redesign networking. |
| **Architectural impact** | Low — stay behind RemoteHost. |
| **Risks** | Op drift vs desktop; listen/preview edge cases. |
| **Sprint size** | **M** |

### 8. Show Patch / timecode-only export UX

| | |
|--|--|
| **User value** | Safer re-export after executors assigned — show day reliability. |
| **Technical complexity** | **S–M** — exporters support modes; UI clarity. |
| **Dependencies** | MA2/MA3 exporters, fixtures. |
| **Architectural impact** | Low. |
| **Risks** | Wrong mode exporting sequences again. |
| **Sprint size** | **S–M** |

### 9. Bundle / missing-media operator polish

| | |
|--|--|
| **User value** | Smoother collect-bundle + relink on laptop/desktop sync. |
| **Technical complexity** | **S–M** — core relink exists. |
| **Dependencies** | media_relink, bundle persistence. |
| **Architectural impact** | Low (watch domain purity if touching relink). |
| **Risks** | Path heal edge cases on Unicode paths. |
| **Sprint size** | **S–M** |

### 10. NDI polish

| | |
|--|--|
| **User value** | Direct NDI without OBS — useful, **not** daily until cues solid. |
| **Technical complexity** | **M–L** — frame sink already; platform/driver pain. |
| **Dependencies** | VideoSync / FrameSink; milestone order says after cue accuracy. |
| **Architectural impact** | Medium — must stay one decode path. |
| **Risks** | Second clock temptation; packaging/DLL; distracts from P0 audio. |
| **Sprint size** | **L** (defer until after Align Anchors / cue accuracy) |

---

## Recommended Sprint 4 feature

### **Song Variants (select one) → then Align / compare**

Canonical design: [`song_variant_design.md`](song_variant_design.md).

1. **Variants foundation** — multiple media packages per song; cues on song; one selected variant feeds `AudioEngine`.  
2. **Later** — Align Anchors / offset / optional compare hear (not simultaneous multi-clock).

MVP out of scope until variants ship: translucent overlay, ripple, auto cross-correlation, per-variant video lane, UI redesign.

---

## Why implement this now

1. **Highest remaining P0 product hole** — replace-only main audio vs versioned mixes.  
2. **Design audited** — Task 1 documents single-file assumptions and schema v2 path.  
3. **Fits architecture** — one buffer / sole clock; ShowSession load retarget; marks untouched.  
4. **Production reliability** — switch beds without rebuilding cues.  

---

## Suggested implementation plan (after design)

See [`song_variant_design.md`](song_variant_design.md) §8–§10 (`I1`–`I8`).

| Task | Goal |
|------|------|
| **I1** | Domain `SongVariant` + helpers + tests |
| **I2** | Schema v2 migrate/load/save |
| **I3** | Retarget main-path helpers (compat mirror `audio_tracks`) |
| **I4–I5** | Select/add variant API + minimal UI |
| **I6** | Docs checkoff |
| **I7+** | Align Anchors / extra media kinds |

---

## Potential future extensions

| Extension | When |
|-----------|------|
| Align Anchors / offset edit | After variants select-one works |
| Semi-transparent waveform overlay | After Align (PRODUCT P1) |
| Multi-anchor / range conform / ripple | After single Align trusted |
| Auto cross-correlation align | P2 research spike |
| Per-variant video / LTC / click media | After audio variants stable |
| Remote select-variant | Via RemoteHost after desktop MVP |
| NDI polish | After cue accuracy + variants P0 |

---

## Sprint 4 Feature progress

| Task | Status |
|------|--------|
| Planning | ✅ Done |
| **Task 1 — Domain & persistence audit / design** | ✅ Done — `song_variant_design.md` |
| **Task 2 — Domain foundation** | ✅ Done — `domain/song_variant.py` + tests |
| **Task 3 — Persistence integration** | ✅ Done — schema v2 + `project_migrations` |
| Task 4 — Playback variant support | ✅ Done — resolve active variant → one buffer |
| Task 5 — Anchor Mapping Foundation | ✅ Done — `domain/anchor_mapping.py` |
| Task 6 — Anchor Playback Integration | ✅ Done — PlaybackService maps Song↔Variant |
| **Sprint 4.5 — Production Validation** | ✅ Done — checklist + debt/risk map (docs only) |
| **Sprint 5 · Task 1 — Song-Time Façade** | ✅ Done — Remote + MainWindow through PlaybackService |
| **Sprint 5 · Task 2 — Align Anchors UX Design** | ✅ Done — `song_variant_design.md` §19 (docs only) |
| **Sprint 5 · Task 3 — Align Anchors Dialog Shell** | ✅ Done — `ui/align_anchors_dialog.py` (no apply) |
| **Sprint 5 · Task 4 — Anchor Computation** | ✅ Done — draft only via `offset_from_anchors` |
| **Sprint 5 · Task 5 — Anchor Apply / Commit** | ✅ Done — undoable `anchor_offset` write |
| **Sprint 5 · Task 6 — Align Anchors Preview** | ✅ Done — ephemeral PlaybackService preview |
| **Sprint 5 · Align Anchors Beta** | ✅ Done — lifecycle / Cancel / Apply / regressions |
| Sprint 6 | **Next** |

---

## Decision log (Sprint 4 Planning)

| Decision | Choice |
|----------|--------|
| Feature Sprint 4 pick | Song Variants (select one) then Align/compare |
| Task 1 framing | Explicit variants model (not simultaneous Reference-first) |
| Task 2 model shape | Flat `SongVariant` (kind+path+anchor_offset); media-bag deferred |
| Task 3 migrations | Isolated in `project_migrations.py`; Repository load/save only |
| Task 4 playback | PlaybackService resolves path; Song owns selection; no Align |
| Task 5 mapping | Domain-only `anchor_mapping`; Song Time canonical; no runtime apply |
| Task 6 playback map | PlaybackService only conversion site; engine gets Variant Time |
| Sprint 4.5 | Docs-only validation; no runtime/UI/playback changes |
| Sprint 5 Task 1 | Close Remote/MainWindow Song-Time bypasses; no Align UI yet |
| Sprint 5 Task 2 | Align UX design only; draft vs applied; marks never move |
| Sprint 5 Task 3 | Dialog shell only; Apply/Preview stubs; no playback change |
| Sprint 5 Task 4 | Draft computation only; Apply still non-destructive |
| Sprint 5 Task 5 | Apply commits via undo command; dirty; marks fixed |
| Sprint 5 Task 6 | Ephemeral preview offset on PlaybackService; Cancel restores |
| Explicitly deferred this slice | NDI, overlay, plugin system, EventBus-as-feature, auto-align |

---

## Sprint 4.5 — Validation summary

Full checklist and debt tables: [`song_variant_design.md`](song_variant_design.md) §17.

| Verdict | Scope |
|---------|--------|
| Ready | Legacy / offset-0 / single-bed desktop workflows (run on-site checklist) |
| Conditional → improved | Non-zero offset: desktop + remote transport façade closed in Sprint 5 Task 1 |
| Not ready | Duration chips; variant CRUD; waveform offset paint |

**Next priority:** Align Anchors Beta Stabilization.

- Façade graph: [`song_variant_design.md`](song_variant_design.md) §18  
- Align UX: [`song_variant_design.md`](song_variant_design.md) §19  
- Dialog shell: [`song_variant_design.md`](song_variant_design.md) §20  
- Draft compute: [`song_variant_design.md`](song_variant_design.md) §21  
- Apply / Commit: [`song_variant_design.md`](song_variant_design.md) §22  
- Preview session: [`song_variant_design.md`](song_variant_design.md) §23  

---

## READY FOR ALIGN ANCHORS BETA
