# Next task

**Status:** Queued — awaiting human start  
**Type:** Feature — MA Export Validation Rules  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 6 Task 1 — MA Export Preflight Domain  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint6MaPreflightDomain.md`  
Baseline: `docs/ma_export_validation.md` (ends READY FOR VALIDATION RULES)

---

## Current task

### Sprint 6 Task 2: Validation Rules

**Do not auto-start until the user explicitly continues.**

### Goal

First MA rule pack (empty/illegal labels, duplicates, executor range, mode info) against a read-only export-intent context. No UI, no XML write, no auto-fix.

### Read first

1. `docs/ma_export_validation.md`
2. `cueplayer.domain.validation`
3. `exporters/plan_from_song.py` (for context field inventory only)

### Done when

- Rules + tests green; REPORT + handoff; STOP
