# Next task

**Status:** Queued — awaiting human start  
**Type:** Architecture / Sprint 3 planning  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 2 Task 8 — ShowSession Foundation  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint2ShowSession.md`  
Baseline: `docs/current_architecture.md` (ends READY FOR SPRINT 3 ARCHITECTURE)

---

## Current task

### Sprint 3 — Architecture planning (kickoff)

**Do not auto-start until the user explicitly continues.**

### Goal

Produce a Sprint 3 plan covering (in recommended order):

1. Event Bus foundation (UI fan-out; do not replace AudioEngine clock)
2. RemoteHost / WebRemote boundary wiring
3. Narrow ShowSession host Protocol (stop duck-typing MainWindow)
4. Optional SettingsService fold-in for web_remote / color / export prefs

### Read first

1. `docs/current_architecture.md`
2. `docs/BOUNDARY_RULES.md` + `docs/MIGRATION_RULES.md`
3. Latest Sprint 2 handoffs under `.ai/handoffs/`

### Out of scope for the planning doc alone

- Implementing Event Bus or RemoteHost in the same planning-only task
  unless the user asks for implementation

### Done when

- Written plan + REPORT + handoff; STOP (or user asks to implement item 1)
