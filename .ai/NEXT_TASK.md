# Next task

**Status:** Queued — awaiting human start  
**Type:** Feature Implementation  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 4 — Feature Planning  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint4FeaturePlanning.md`  
Baseline: `docs/roadmap.md` (ends READY FOR FEATURE IMPLEMENTATION)

---

## Current task

### Sprint 4 Feature — Task 1: Domain & persistence audit (Reference tracks)

**Do not auto-start until the user explicitly continues.**

### Goal

Confirm `AudioTrack` Main/Reference roles, offset, mute/solo/hide/lock round-trip
for multi-audio Align Anchors MVP. Add gaps only if required. No timeline UX yet
unless needed for tests.

### Read first

1. `docs/roadmap.md`
2. `docs/PRODUCT_SPEC.md` (multi-audio / Align Anchors)
3. `domain/models.py` (`AudioTrack`)
4. `persistence/project_store.py`

### In scope

- Domain/persistence audit + tests for multi-track songs
- Minimal model fixes if round-trip broken

### Out of scope

- Full timeline Reference paint (Task 2+)
- Overlay / ripple / auto-correlation
- NDI, EventBus adoption, UI redesign

### Done when

- Multi-track song JSON round-trip covered; REPORT + handoff; STOP
