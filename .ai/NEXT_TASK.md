# Next task

**Status:** Queued — awaiting human start  
**Type:** Feature Implementation — Song Variants  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 4 Feature Task 1 — Song Variant design  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint4SongVariantDesign.md`  
Baseline: `docs/song_variant_design.md` (ends READY FOR SONG VARIANT IMPLEMENTATION)

---

## Current task

### Sprint 4 Feature — I1: Domain SongVariant types + helpers

**Do not auto-start until the user explicitly continues.**

### Goal

Add `SongVariant` / `SongVariantMedia` and Song fields/helpers with unit tests.
Prefer no playback behavior change yet; schema migrate may be I2 in the same or
next task.

### Read first

1. `docs/song_variant_design.md`
2. `docs/roadmap.md`
3. `domain/models.py` (`Song`, `AudioTrack`)
4. `persistence/project_store.py`

### In scope

- Domain types + helpers + tests
- Optional: schema v2 migrate if tightly scoped

### Out of scope

- UI redesign
- Align Anchors UI
- Intentional playback behavior changes beyond accessors
- EventBus adoption

### Done when

- Variants model + tests green; REPORT + handoff; STOP
