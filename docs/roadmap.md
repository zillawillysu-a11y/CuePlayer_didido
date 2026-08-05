# CuePlayer — Product & Architecture Roadmap

**Status:** Sprint 8 Task 2 — Video Track Responsiveness  
**Updated:** 2026-08-05  
**Scope tip:** `cursor/sprint8-video-responsive-028d`  
**Related:** [`playback_performance_audit.md`](playback_performance_audit.md) · [`PERFORMANCE_RULES.md`](PERFORMANCE_RULES.md) · [`production_soak.md`](production_soak.md) · [`ma_preflight.md`](ma_preflight.md) · [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md) · [`song_variant_design.md`](song_variant_design.md) · [`AGENTS.md`](../AGENTS.md)

---

## Planning principles

Prioritize by:

1. **Daily workflow improvement** — programming / show-prep hours saved every day  
2. **Production reliability** — cue accuracy, clock integrity, export safety  
3. **Long-term maintainability** — fits strangler seams; no god-object growth  

**Exclude from Feature Sprints:** large rewrites, plugin systems, major UI redesigns, cosmetic-only work, architecture-only tasks (EventBus adoption is spine work, not the Feature pick).

**Hard product rules still apply:** sole `AudioEngine` clock; Unicode paths; Display Name ≠ MA Export Name; no Chinese in MA XML labels; Main = Go+ with CueDestination; Top Button = shared 2-cue self-release.

**Prefer features that strengthen:** professional lighting workflow · MA3 integration · executor workflow · Timeline workflow · production reliability.

---

## Post–Sprint 5 product snapshot

| Area | State |
|------|--------|
| Song Variants (select one) + persistence | ✅ Production |
| Song-Time façade + PlaybackService mapping | ✅ Production |
| Align Anchors (draft / preview / Apply / undo / beta) | ✅ Production complete |
| MA2 / MA3 exporters + Show Patch + golden fixtures | ✅ Exist |
| MA Preflight (domain → rules → report → UI → export gate) | ✅ Production MVP |
| Timecode-only re-export mode | ✅ Exporter/UI present; operator clarity gaps |
| Variant CRUD / picker UI | ⚠️ Debt — Align works; management chrome thin |
| Simultaneous Reference overlay / ripple | Deferred (P1) |
| NDI / OSC / plugin system | Deferred |

**Implication:** Variants + Align + Preflight export gate are ready for **real-world soak**. Next Feature Sprint waits on desk evidence ([`production_soak.md`](production_soak.md)).

---

## Sprint 6 — Top 10 feature opportunities

Sprint size key: **S** ≈ 1 focused task · **M** ≈ 2–4 tasks · **L** ≈ full Feature Sprint · **XL** = split before starting.

Effort below is **relative implementation weight** (components touched / invasiveness), not calendar time.

### 1. MA Export Preview / Validation — **recommended Sprint 6**

| | |
|--|--|
| **User value** | See Sequence / Executor / Cue / Timecode labels before XML hits the console; fix pinyin/illegal chars and collisions without onPC round-trips. Direct P1 in PRODUCT_SPEC. |
| **Frequency of use** | **Every export** — programming sessions and show-day re-exports. |
| **Architectural readiness** | **High** — `exporters/*`, `plan_from_song`, Show Patch, Display vs MA name, sanitize helpers already ship. |
| **Estimated effort** | **M** — thin application helper + dialog over existing export plan; no exporter rewrite. |
| **Risks** | Preview drift from real export; Chinese-in-label regressions; over-editing beyond name overrides. |
| **Dependencies** | Exporters, Show Patch profile, undo for name edits (prefer existing song/mark fields). |
| **Fits priorities** | Lighting · MA3 · Executors · Reliability |

### 2. Variant management UI (CRUD + picker)

| | |
|--|--|
| **User value** | Add / rename / enable / select / remove audio variants without file-replace rituals; completes daily Align workflow. |
| **Frequency of use** | High during prep; medium mid-show. |
| **Architectural readiness** | **High** — domain + persistence + playback already done. |
| **Estimated effort** | **M** — UI + light undo; avoid Timeline redesign. |
| **Risks** | Accidental delete of selected bed; path/missing-media edge cases. |
| **Dependencies** | `SongVariant`, Align dialog, ShowSession load path. |
| **Fits priorities** | Timeline · Reliability (secondary to MA handoff) |

### 3. Show Patch / Timecode-only export clarity

| | |
|--|--|
| **User value** | Safer show-day re-export after executors already assigned; fewer accidental full Sequence rewrites. |
| **Frequency of use** | High on show day; medium in tech. |
| **Architectural readiness** | **High** — modes exist (`full` / `timecode_only`); UI could be clearer. |
| **Estimated effort** | **S–M** — copy, confirmations, preview of what will be written. |
| **Risks** | Wrong mode still exporting sequences; MA2 vs MA3 wording confusion. |
| **Dependencies** | Show Patch page, Export dialog, exporters. |
| **Fits priorities** | MA3 · Executors · Reliability |

### 4. Export latency compensation UX

| | |
|--|--|
| **User value** | Operators set LTC→MA delay (−0.10s / −0.20s) confidently; fewer mistimed looks on console. |
| **Frequency of use** | Medium (per show / venue); critical when used. |
| **Architectural readiness** | **High** — export layer already supports `ltc_latency_compensation_seconds`. |
| **Estimated effort** | **S–M** — surface in Show Patch / Export + preview of shifted events. |
| **Risks** | Double-applying delay; confusing Song Time vs TC Slot offset. |
| **Dependencies** | Exporters, Show Patch. |
| **Fits priorities** | Lighting · MA3 · Reliability |

### 5. Video ↔ music alignment UX polish

| | |
|--|--|
| **User value** | Faster clip nudge / hide Video+LTC after align / sync-calib clarity — daily VJ programming. |
| **Frequency of use** | High for VJ-heavy shows; medium otherwise. |
| **Architectural readiness** | **High** — sample-locked clips exist. |
| **Estimated effort** | **S–M** — gestures/affordances only. |
| **Risks** | Playhead jank; accidental second decode path. |
| **Dependencies** | Timeline, VideoSync. |
| **Fits priorities** | Timeline · Reliability |

### 6. Setlist Sheet → MA3 handoff polish

| | |
|--|--|
| **User value** | Faster copy of order / names / TC / notes into MA3 sheets; fewer transcription errors. |
| **Frequency of use** | High at show build. |
| **Architectural readiness** | **High** — Setlist Sheet page exists. |
| **Estimated effort** | **S–M** — columns, copy formats, MA-safe name column. |
| **Risks** | Competing with Export Preview as the “source of truth” for names. |
| **Dependencies** | Setlist Sheet, MA Export Name fields. |
| **Fits priorities** | MA3 · Lighting |

### 7. Bundle / missing-media operator polish

| | |
|--|--|
| **User value** | Smoother collect-bundle + relink across laptop/desktop — production continuity. |
| **Frequency of use** | Medium; spikes on venue change. |
| **Architectural readiness** | **Medium–High** — relink/bundle exist. |
| **Estimated effort** | **S–M**. |
| **Risks** | Unicode path heal edge cases. |
| **Dependencies** | media_relink, persistence. |
| **Fits priorities** | Reliability |

### 8. Simultaneous Reference waveform overlay (compare hear)

| | |
|--|--|
| **User value** | See old/new mix aligned after Align Anchors — PRODUCT P1 version-revision path. |
| **Frequency of use** | Medium–high in prep; lower once aligned. |
| **Architectural readiness** | **Medium** — Align offset done; paint/cache not offset-aware; must stay one clock. |
| **Estimated effort** | **L** — Timeline/Waveform paint + A/B solo policy; easy to balloon. |
| **Risks** | Second buffer/clock temptation; paint jank; scope creep into ripple/conform. |
| **Dependencies** | Align Anchors, waveform cache. |
| **Fits priorities** | Timeline (heavy); do **after** export confidence |

### 9. Web Remote UX polish

| | |
|--|--|
| **User value** | iPad programming comfort after RemoteHost boundary. |
| **Frequency of use** | Medium for remote programmers. |
| **Architectural readiness** | **High** — stay behind RemoteHost. |
| **Estimated effort** | **S–M**. |
| **Risks** | Op drift vs desktop. |
| **Dependencies** | RemoteHost, Song-Time façade. |
| **Fits priorities** | Timeline (secondary) |

### 10. NDI polish

| | |
|--|--|
| **User value** | Direct NDI without OBS — useful, not daily until cue/export solid. |
| **Frequency of use** | Low–medium until venue requires it. |
| **Architectural readiness** | **Medium** — frame sink exists; packaging pain. |
| **Estimated effort** | **L**. |
| **Risks** | Second clock; DLL/packaging; distracts from P0 lighting path. |
| **Dependencies** | VideoSync / FrameSink. Milestone order: after cue accuracy. |
| **Fits priorities** | Defer |

---

## Recommended Sprint 6 feature

### **MA Export Preview / Validation (MVP)**

Ship a read-mostly **Export Preview** over the existing export plan:

1. List Sequences, Executors, Cue labels (Display + MA Export Name), Timecode events.  
2. Flag illegal characters, empties, duplicates, out-of-range pool/executor assignments.  
3. Allow editing **MA Export Name** (and clear conflicts) without rewriting Chinese Display Names.  
4. Preview differences for **full** vs **timecode_only** modes.  
5. Keep exporters as source of truth — preview consumes the same plan builders used to write XML.

**MVP out of scope:** new export formats, console network push, full Show Patch redesign, waveform overlay, EventBus adoption, NDI.

---

## Why this feature should come next

1. **Closes the highest remaining professional gap** — programmers now trust Align; they still fear silent MA label/executor failures on import.  
2. **PRODUCT_SPEC P1 #1** — Export Preview / Validation is explicitly first after core.  
3. **Architectural readiness is highest** — plan/export/Show Patch already exist; work is UI + validation over known seams.  
4. **Daily + show-day frequency** — every export benefits; show-day timecode-only re-exports benefit most.  
5. **Strengthens MA3 / executor workflow** without Timeline redesign or architecture theater.  
6. **Production reliability** — catch Chinese-in-label / duplicate executor / bad CueDestination issues before onPC.  
7. **Natural sequencing** — Variant CRUD and overlay compare are valuable next, but less urgent than “will the console accept this show?”

---

## Proposed implementation phases (Sprint 6)

| Phase | Goal | Notes |
|-------|------|-------|
| **P0 — Audit** | Document export-plan fields + validation rules (illegal chars, dupes, ranges, mode diffs) | Docs + inventory of `plan_from_song` / Show Patch |
| **P1 — Preview shell** | Modal/dialog: read-only tables for sequences / executors / cues / TC events | No XML write; same plan as export |
| **P2 — Validation** | Inline errors/warnings; block or warn on export | Never write Chinese into MA labels |
| **P3 — Editable names** | Edit MA Export Name from preview; persist on song/marks; undo | Display Name untouched |
| **P4 — Mode clarity** | Full vs Timecode-only summary; confirm before write | Ties Show Patch + Export dialog |
| **P5 — Tests + checklist** | Unit tests on validators; golden plan fixtures; operator checklist | No exporter schema rewrite |

Optional stretch (only if P0–P5 solid): surface **latency compensation** in the same preview (Phase P4b).

---

## Long-term product vision after this feature

```text
Today (post–Sprint 5)
  Song Time cues + Align Anchors + select-one variants
        │
Sprint 6
  Export Preview / Validation → confident MA2/MA3 handoff
        │
Next Feature Sprints (likely order)
  Variant CRUD UI → daily mix management without file hacks
  Timecode-only / latency UX polish (if not absorbed in Sprint 6)
  Reference overlay / A-B compare (still one clock)
  Video alignment UX / Sheet→MA3 polish as needed
        │
Later
  OSC / MA3 remote transport · Bundle excellence · NDI
  Multi-anchor / ripple only after single-offset compare is trusted
```

**North star:** CuePlayer remains the **lighting programmer’s Song-Time desk** — hear the right mix, mark once, preview MA labels, export XML the console accepts — without a second clock or a Chinese-in-XML footgun.

---

## Sprint 4–5 Feature progress (complete)

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
| **Sprint 5 · Task 3 — Align Anchors Dialog Shell** | ✅ Done — `ui/align_anchors_dialog.py` |
| **Sprint 5 · Task 4 — Anchor Computation** | ✅ Done — draft via `offset_from_anchors` |
| **Sprint 5 · Task 5 — Anchor Apply / Commit** | ✅ Done — undoable `anchor_offset` write |
| **Sprint 5 · Task 6 — Align Anchors Preview** | ✅ Done — ephemeral PlaybackService preview |
| **Sprint 5 · Align Anchors Beta** | ✅ Done — lifecycle / Cancel / Apply / regressions |
| **Sprint 6 · Product Planning** | ✅ Done — this document (historical pick) |
| **Sprint 6 · Task 1 — Preflight Domain** | ✅ Done — `domain/validation` + `ma_preflight.md` |
| **Sprint 6 · Task 2 — Validation Rules** | ✅ Done — `ma_preflight_rules()` MVP pack |
| **Sprint 6 · Task 3 — Preflight Report Builder** | ✅ Done — `PreflightReport` presentation layer |
| **Sprint 6 · Task 4 — Preflight UI** | ✅ Done — Tools → MA Preflight… |
| **Sprint 6 · Task 5 — Export Integration** | ✅ Done — Show Patch preflight gate |
| **Sprint 7 · Production Soak Planning** | ✅ Done — [`production_soak.md`](production_soak.md) |
| Sprint 7 · Real-world validation | Ongoing (operators) |
| **Sprint 8 · Task 1 — Perf audit + experimental hide** | ✅ Done — [`playback_performance_audit.md`](playback_performance_audit.md) |
| **Sprint 8 · Task 2 — Video Track responsiveness** | ✅ Done — async latest-wins decode + paint-before-quiesce |
| Sprint 8 · Tasks 3–5 — Further measured optimizations | **Next** |

---

## Decision log

| Decision | Choice |
|----------|--------|
| Feature Sprint 4 pick | Song Variants (select one) then Align/compare |
| Sprint 5 | Align Anchors UX → shell → compute → Apply → Preview → Beta |
| **Sprint 6 Feature pick** | **MA Export Preview / Validation (MVP)** |
| Sprint 6 Task 1 | Domain validation framework only (`ValidationReport` / rules registry) |
| Sprint 6 Task 2 | MA Preflight rule pack MVP (read-only; no exporters/UI) |
| Sprint 6 Task 3 | Preflight Report Builder (`PreflightReport` / sort / serialize) |
| Sprint 6 Task 4 | Preflight UI (`MaPreflightDialog`; read-only) |
| Sprint 6 Task 5 | Export Integration (gate on `ValidationReport.has_errors`) |
| **Sprint 7** | Production soak (Variants + Align + Preflight) — docs then real shows |
| **Sprint 8 pick** | Playback smoothness (audit first; then measured Tasks 2–5) |
| Sprint 8 Task 1 | Hide Align/Preflight Tools entries; perf diagnostics only |
| Sprint 8 Task 2 | Video off-UI latest-wins decode; song chrome before quiesce |
| Sprint 6 explicitly deferred | Overlay compare, NDI, OSC, EventBus-as-feature, variant CRUD (runner-up), large UI redesign |
| Why not overlay next | Align is done, but console handoff risk > paint polish for lighting shows |
| Why not variant CRUD first | Domain ready, but export confidence unblocks more shows per week |
| Why soak before Feature Sprint 7 | Evidence over speculation; measure force-export / CRUD / Preflight friction on desk |

---

## Sprint 4.5 — Validation summary (historical)

Full checklist: [`song_variant_design.md`](song_variant_design.md) §17–§24.

| Verdict | Scope |
|---------|--------|
| Ready | Legacy / offset-0 / Align Anchors desktop workflows |
| Conditional → improved | Non-zero offset façade closed in Sprint 5 Task 1 |
| Still polish | Duration chips; variant CRUD chrome; waveform offset paint |

---

## Historical note — Sprint 4 planning framing

Earlier Sprint 4 recommendation was **Song Variants → Align Anchors** (see git history / `song_variant_design.md`). That Feature Sprint is **complete**. Sprint 6 planning above supersedes “next = Align” language.

---

## Sprint 6 Task 1 — Preflight Domain (done)

See [`ma_preflight.md`](ma_preflight.md).

## Sprint 6 Task 2 — Validation Rules (done)

See [`ma_preflight.md`](ma_preflight.md) § Task 2.

## Sprint 6 Task 3 — Preflight Report Builder (done)

See [`ma_preflight.md`](ma_preflight.md) § Task 3.

## Sprint 6 Task 4 — Preflight UI (done)

See [`ma_preflight.md`](ma_preflight.md) § Task 4.

## Sprint 6 Task 5 — Export Integration (done)

See [`ma_preflight.md`](ma_preflight.md) § Task 5.

## Sprint 7 — Production Soak Planning (done)

Canonical plan: [`production_soak.md`](production_soak.md).

Covers Song Variant, Align Anchors, and MA Preflight: checklist, test matrix (new/legacy/large/variants/export/recovery/media/undo/perf), risks, metrics, and Feature Planning priorities.

## Sprint 8 Task 1 — Playback Performance Audit + Experimental Hide (done)

See [`playback_performance_audit.md`](playback_performance_audit.md) · [`PERFORMANCE_RULES.md`](PERFORMANCE_RULES.md).

- Tools → Align Anchors / MA Preflight hidden via `ENABLE_EXPERIMENTAL_FEATURES=False`.
- Optional `CUEPLAYER_PERF=1` diagnostics; no speculative optimizations.

## Sprint 8 Task 2 — Video Track Responsiveness

- Round 1: async latest-wins + paint-before-quiesce (~50% desk improve).
- Round 2: Timeline/playhead acceptance; prove pipeline; lock_timeout.
- Round 3: **Live scrub preview** (~16 FPS) + **fast final-land** on release
  (async exact land only — no UI-thread sync try).
- Round 4: **Final-land priority + resume** — pipeline states, engine gated
  during `FINAL_LANDING`, land cannot be overwritten by play, resume after
  exact land (fixes 1–4 s land delay + second freeze).
- Round 5: **Empty-frame + recovery** — explicit release target outcomes,
  no accidental black, bounded retries (≤5 / 500 ms), resume watchdog,
  decoder reset after repeated empties.
- Round 6: **Scrub preview delivery + deterministic resume** — session vs
  request generation; present in-flight preview within tolerance; engine
  gated during scrub; `resume_required` invariant with recovery; separate
  play/scrub decoder contexts.
- Round 7: **State-machine trace (diagnosis only)** — `VIDEO_SM` events for
  scrub → land → resume → play; identify post-land freeze without redesign.
  See [`video_sm_freeze_diagnosis.md`](video_sm_freeze_diagnosis.md).
- Round 8: **Post-land submit + playback lateness** — Windows confirmed
  Root Cause A (IDLE + fake fanout, no submit) and B (gen starvation).
  Immediate post-land play submit; pending-latest for PLAYBACK; no gen bump
  on ordinary clock; present within lateness tolerance.
- Round 8b: **Deterministic seek** — position-dependent freezes (GOP/handoff);
  explicit playback-decoder handoff; seek deadline recreate; no empty black
  widget while Video exists; seek telemetry (`video.seek.*`).
- **Dense Mark region** — A/B fan-out instrumentation; indexed Mark lookup;
  viewport paint; NOW skip-if-unchanged. See [`dense_mark_perf.md`](dense_mark_perf.md).
- **Instrumentation fix** — scrub path now records fan-out (empty Windows dumps);
  LIVE CHECK in report; seek GOP notes. See
  [`dense_mark_instrumentation_fix.md`](dense_mark_instrumentation_fix.md).

**Next:** Windows re-dump with LIVE CHECK OK — then interpret sparse vs dense.
Do not optimize further until measurements are valid.

---

## READY FOR WINDOWS DENSE MARK INSTRUMENTATION VALIDATION
