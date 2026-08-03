# Next task

**Status:** Queued — awaiting human start  
**Type:** Feature — Anchor Apply / Commit  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 5 Task 4 — Anchor Computation (draft only)  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint5AnchorComputation.md`  
Baseline: `docs/song_variant_design.md` §21 (ends READY FOR ANCHOR APPLY)

---

## Current task

### Sprint 5 Task 5: Anchor Apply / Commit

**Do not auto-start until the user explicitly continues.**

### Goal

Persist dialog draft_offset to SongVariant.anchor_offset with dirty/undo.
Marks never move. Optional playback preview session.

### Read first

1. `docs/song_variant_design.md` §21.4
2. `ui/align_anchors_dialog.py`
3. PlaybackService mapping façade

### Done when

- Apply persists; tests green; REPORT + handoff; STOP
