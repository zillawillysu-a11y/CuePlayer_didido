# Next task

**Status:** Queued — awaiting human start  
**Type:** Architecture / Event Bus foundation  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 3 Task 2 — Remote Boundary Foundation  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint3RemoteBoundary.md`  
Baseline: `docs/current_architecture.md` (ends READY FOR EVENT BUS FOUNDATION)

---

## Current task

### Sprint 3 — Task 3: Event Bus foundation

**Do not auto-start until the user explicitly continues.**

### Goal

Introduce a narrow typed Event Bus for UI fan-out (chrome / dirty / marks).
Do **not** replace `AudioEngine` as the playback clock.
Do **not** redesign Remote features or networking.

### Read first

1. `docs/current_architecture.md`
2. `docs/BOUNDARY_RULES.md` + `docs/MIGRATION_RULES.md`
3. `.ai/handoffs/2026-08-03_Sprint3RemoteBoundary.md`

### In scope

- Event Bus type + minimal publishers/subscribers for a small chrome set
- Tests + docs

### Out of scope

- Second clock / position bus
- Remote feature redesign
- MainWindow god-object rewrite

### Done when

- Bus exists and is used for a narrow fan-out path without clock semantics;
  REPORT + handoff; STOP
