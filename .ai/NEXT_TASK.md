# Next task

**Status:** Queued — awaiting human start  
**Type:** Feature — Anchor Computation  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 5 Task 3 — Align Anchors Dialog Shell  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint5AlignAnchorsShell.md`  
Baseline: `docs/song_variant_design.md` §20 (ends READY FOR ANCHOR COMPUTATION)

---

## Current task

### Sprint 5 Task 4: Anchor Computation

**Do not auto-start until the user explicitly continues.**

### Goal

Wire Song/Variant anchor capture and `draft = song_anchor − variant_anchor`
via `domain.anchor_mapping`. Update draft display/nudges. Prefer still deferring
Apply persistence if scoped that way — follow the user task text.

### Read first

1. `docs/song_variant_design.md` §19–§20
2. `ui/align_anchors_dialog.py`
3. `domain/anchor_mapping.py`

### Done when

- Computation + tests; REPORT + handoff; STOP
