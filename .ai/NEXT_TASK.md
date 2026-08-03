# Next task

**Status:** Queued — awaiting human start  
**Type:** Architecture / Playback service  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 1 Task 4 — `ProjectRepository`  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint1ProjectRepository.md`  
Baseline: `docs/current_architecture.md` (ends READY FOR PLAYBACK SERVICE)

---

## Current task

### Sprint 1 — Task 5: Playback service foundation

**Do not auto-start until the user explicitly continues.**

### Goal

Extract a thin application playback / song-session service for orchestration
currently in `MainWindow` (song activate refresh order, transport helpers)
**without** changing `AudioEngine` internals, sample-clock rules, or UI design.

### Read first

1. `docs/current_architecture.md` (playback flow §13, plan Task 5)
2. `docs/BOUNDARY_RULES.md` + `docs/MIGRATION_RULES.md`
3. `AGENTS.md` clock non-negotiables
4. `MainWindow._activate_song` + engine wiring

### In scope

- New application service module
- MainWindow delegates orchestration calls
- Tests for song switch / transport smoke where practical

### Out of scope

- Redesigning AudioEngine / mixer / av_path_lock policy
- RemoteHost, Repository expansions, features

### Done when

- Orchestration lives in service; clock rule intact; tests green; REPORT + handoff; STOP
