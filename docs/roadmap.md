# CuePlayer — Product & Architecture Roadmap

**Status:** Sprint 4 Feature Planning complete (docs only — no implementation)  
**Updated:** 2026-08-03  
**Scope tip:** `cursor/sprint4-feature-planning-028d`  
**Related:** [`architecture_overview.md`](architecture_overview.md) · [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md) · [`current_architecture.md`](current_architecture.md) · [`AGENTS.md`](../AGENTS.md)

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

### 1. Multi-audio Reference lanes + Align Anchors (MVP) — **RECOMMENDED Sprint 4**

| | |
|--|--|
| **User value** | Compare old/new music beds on one timeline; lock offsets with Anchors — core P0 still missing while replace-only main audio dominates daily work. |
| **Technical complexity** | **M–L** — domain `AudioTrack` + `offset_seconds` exist; timeline paint + mute/solo + align action are new UX surface. |
| **Dependencies** | Existing timeline waveform path; PlaybackService mute/volume; ShowSession activate; persistence already stores tracks. |
| **Architectural impact** | Low–medium. Extends domain/UI; should route mute/solo through PlaybackService; avoid growing MainWindow orchestration. Benefits from ShowSession song bind. |
| **Risks** | Scope creep into overlay/ripple (P1); second waveform cache contention; A/B solo edge cases with LTC strip. |
| **Sprint size** | **L** (MVP: Main + ≥1 Reference, mute/solo/hide, offset nudge, Align Anchors) |

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

### **Multi-audio Reference lanes + Align Anchors (MVP)**

Ship the smallest useful version of PRODUCT_SPEC P0 multi-audio comparison:

- Keep one **Main** music bed (clock source unchanged).
- Show **≥1 Reference** audio lane with waveform, mute / solo / hide / lock, color, name.
- Persist `offset_seconds` (already on `AudioTrack`).
- **Align Anchors:** place an anchor on Main and Reference; command shifts Reference offset so anchors coincide.
- Frame / ms nudge of selected track offset (reuse nudge patterns where possible).
- **Out of Sprint 4 MVP:** translucent overlay, multi-anchor ripple, auto cross-correlation (P1/P2), replace Main with Reference without explicit action.

---

## Why implement this now

1. **Highest remaining P0 product hole** after timeline/marks/video/LTC/MA — AGENTS still lists version-comparison workflow as incomplete vs replace-only.  
2. **Daily workflow** for lighting programmers comparing revisions before cueing.  
3. **Fits new architecture:** domain tracks exist; PlaybackService can own mute/solo; ShowSession already binds song media; no EventBus/clock redesign required.  
4. **Production reliability:** correct offset before marks/export beats polish chrome.  
5. **Maintainability:** forces track list to stay in domain/persistence rather than inventing parallel UI-only state.  
6. NDI and overlays wait; selection colors and Export Preview are valuable but smaller than closing this P0 gap.

---

## Suggested implementation plan (Task 1–N)

| Task | Goal | Done when |
|------|------|-----------|
| **T1 — Domain & persistence audit** | Confirm `AudioTrack` fields, roles (Main/Reference), offset, mute/solo/hide/lock round-trip; add gaps only if required | Fixtures/tests for multi-track song JSON |
| **T2 — Timeline Reference lane paint** | Paint Reference waveforms under Main; LTC strip rules unchanged on Main | Visual + unit/UI tests; no second clock |
| **T3 — Track chrome controls** | Mute/solo/hide/lock/name/color for Reference via existing patterns; solo keeps shared playhead | PlaybackService used for mute/solo where applicable |
| **T4 — Offset edit** | Nudge / numeric offset for selected Reference; undo command | Offset persists; undo/redo works |
| **T5 — Align Anchors MVP** | Set anchors on Main + Reference; Align command computes Δt → Reference.offset | Golden test on known offset; Unicode paths OK |
| **T6 — Setlist / song UX glue** | Add/remove Reference file; switch songs via ShowSession without losing tracks | Activate/deactivate preserves tracks |
| **T7 — Docs + regression** | PRODUCT_SPEC/AGENTS note; full suite | Roadmap checked off; no LTC/clock regressions |

Optional parallel **architecture spine** (not Feature scope): discrete Playback EventBus events — only if it unblocks mute/solo fan-out without blocking T1–T7.

---

## Potential future extensions

| Extension | When |
|-----------|------|
| Semi-transparent waveform overlay | After MVP Reference lanes stable (PRODUCT P1) |
| Multi-anchor / range conform / ripple | After single Align Anchors trusted |
| Auto cross-correlation align | P2 research spike |
| A/B replace Main from Reference (explicit) | After operators trust offsets |
| Remote control of Reference mute/solo | Via RemoteHost after desktop MVP |
| MediaJobQueue extraction for detect UX | Separate Feature/arch slice |
| NDI polish | After cue accuracy + multi-audio P0 |

---

## Sprint 4 architecture spine (non-Feature)

Keep on backlog; do **not** substitute for the Feature pick:

1. Playback events on `EventBus` (discrete; no playhead ticks)  
2. Optional remote transport via PlaybackService  
3. Optional ShowHost/RemoteHost façades  
4. Optional SettingsService fold-in  

---

## Decision log (Sprint 4 Planning)

| Decision | Choice |
|----------|--------|
| Feature Sprint 4 pick | Multi-audio Reference + Align Anchors MVP |
| Explicitly deferred this sprint | NDI polish, overlay, plugin system, UI redesign, EventBus-as-feature |
| Runner-up if MVP too large | Video ↔ music alignment UX polish (**M**) or row-color consistency (**S–M**) |

---

## READY FOR FEATURE IMPLEMENTATION
