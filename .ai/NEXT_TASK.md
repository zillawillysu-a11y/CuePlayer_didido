# Next task

**Status:** Queued — awaiting human start  
**Type:** Architecture / Service Layer  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 1 Task 2 — Transitional Layer Cleanup  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint1TransitionalCleanup.md`  
Baseline: `docs/current_architecture.md` (ends READY FOR SERVICE LAYER)

---

## Current task

### Sprint 1 — Task 3: Service Layer (first extract)

**Do not auto-start until the user explicitly continues.**

### Goal

Extract **`application/project_service`** (open / save / save-as / dirty / autosave
orchestration) from `MainWindow` with **identical** behavior. No Repository
pattern. No RemoteHost wiring. No UI redesign.

### Read first

1. `docs/current_architecture.md` (§12 save/load, §15, Sprint 1 plan Task 3)
2. `docs/BOUNDARY_RULES.md` + `docs/MIGRATION_RULES.md`
3. `docs/ARCHITECTURE_TARGET.md` step for `application/project_service`
4. `CHANGELOG.md` (Unreleased / Task 2)

### In scope

- New `cueplayer.application` package with project service
- MainWindow delegates; dialogs stay in UI
- Tests for persistence / smoke save-load paths

### Out of scope

- Repository classes
- RemoteHost / bridge private-API rewrite
- adapters/ renames, features, behavior changes

### Done when

- Service owns orchestration; behavior unchanged
- Full or targeted tests green
- REPORT + handoff; STOP
