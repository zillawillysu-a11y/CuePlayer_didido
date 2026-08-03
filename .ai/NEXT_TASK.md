# Next task

**Status:** Queued — awaiting human start  
**Type:** Architecture / Repository layer  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 1 Task 3 — Application `ProjectService`  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint1ProjectService.md`  
Baseline: `docs/current_architecture.md` (ends READY FOR REPOSITORY LAYER)

---

## Current task

### Sprint 1 — Task 4: Repository layer (thin ProjectStore adapter)

**Do not auto-start until the user explicitly continues.**

### Goal

Introduce a thin repository / adapter implementing `ports.ProjectStore` that
wraps existing `persistence.project_store.load_project` / `save_project`.
Point `ProjectService` at it. **No** behavior or schema changes.

### Read first

1. `docs/current_architecture.md` (plan Task 4)
2. `docs/BOUNDARY_RULES.md` + `docs/MIGRATION_RULES.md`
3. `src/cueplayer/ports/project_store.py`
4. `src/cueplayer/application/project_service.py`

### In scope

- Adapter class + wire into `ProjectService`
- Tests proving identical load/save

### Out of scope

- New persistence features, migrations, RemoteHost, song_session
- UI redesign

### Done when

- Service uses port/adapter; tests green; REPORT + handoff; STOP
