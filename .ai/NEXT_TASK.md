# Next task

**Status:** Queued — awaiting human start  
**Type:** Feature — Anchor Playback Integration  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 4 Feature Task 5 — Anchor Mapping Foundation  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint4AnchorMapping.md`  
Baseline: `docs/song_variant_design.md` (ends READY FOR ANCHOR PLAYBACK INTEGRATION)

---

## Current task

### Sprint 4 Feature Task 6: Anchor Playback Integration

**Do not auto-start until the user explicitly continues.**

### Goal

Apply `domain.anchor_mapping` for the selected variant during seek / media
index / (optional) waveform paint. AudioEngine remains sole clock. No Align UI.

### Read first

1. `docs/song_variant_design.md` §15
2. `domain/anchor_mapping.py`
3. PlaybackService seek / ShowSession load paths

### Done when

- Runtime uses mapping; tests green; REPORT + handoff; STOP
