# Next task

**Status:** Queued — awaiting human start  
**Type:** Architecture / Remote boundary  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 3 Task 1 — ShowHost Protocol Foundation  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint3ShowHostProtocol.md`  
Baseline: `docs/current_architecture.md` (ends READY FOR REMOTE BOUNDARY)

---

## Current task

### Sprint 3 — Task 2: Remote boundary

**Do not auto-start until the user explicitly continues.**

### Goal

Make Web Remote talk only through `ports.RemoteHost` (expand as needed),
removing duck-typed MainWindow private API usage from `web_remote.bridge`.

### Read first

1. `docs/current_architecture.md`
2. `docs/BOUNDARY_RULES.md` + `docs/MIGRATION_RULES.md`
3. `ports/remote_host.py`, `web_remote/bridge.py`

### In scope

- Expand / implement RemoteHost
- Retarget bridge call sites
- Tests

### Out of scope

- EventBus, ShowSessionService redesign, PlaybackService redesign

### Done when

- Bridge no longer needs MainWindow `_` privates for supported ops; REPORT + handoff; STOP
