# Next task

**Status:** Queued — awaiting human start  
**Type:** Feature — Song Variant persistence  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 4 Feature Task 2 — Song Variant domain foundation  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint4SongVariantDomain.md`  
Baseline: `docs/song_variant_design.md` (ends READY FOR PERSISTENCE INTEGRATION)

---

## Current task

### Sprint 4 Feature Task 3: Persistence integration

**Do not auto-start until the user explicitly continues.**

### Goal

Persist `Song.variants` / `selected_variant_id` (schema v2), migrate from
legacy `audio_tracks`, round-trip fixtures. No UI redesign; no intentional
playback behavior change.

### Read first

1. `docs/song_variant_design.md`
2. `domain/song_variant.py` / `domain/models.py`
3. `persistence/project_store.py`

### Done when

- Schema v2 load/save + migration tests green; REPORT + handoff; STOP
