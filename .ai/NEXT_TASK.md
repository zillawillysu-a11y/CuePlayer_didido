# Next task

**Status:** Queued — awaiting human start  
**Type:** Architecture / Event Bus  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 2 Task 7 — Settings Service Foundation  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint2SettingsService.md`  
Baseline: `docs/current_architecture.md` (ends READY FOR EVENT BUS FOUNDATION)

---

## Current task

### Sprint 2 — Task 8: Event Bus foundation

**Do not auto-start until the user explicitly continues.**

### Goal

Introduce a thin in-process application event bus to reduce MainWindow signal
fan-out for high-value domain/UI events, without redesigning Qt widgets or
replacing the AudioEngine sample clock.

### Read first

1. `docs/current_architecture.md` (plan Task 8)
2. `docs/BOUNDARY_RULES.md` + `docs/MIGRATION_RULES.md`
3. MainWindow signal wiring around playhead / dirty / song activate

### In scope

- Event bus module + a small set of migrated subscriptions
- Tests

### Out of scope

- Replacing AudioEngine `position_changed` / `playing_changed` as the clock
- Settings / Playback / RemoteHost redesign
- ShowSessionService

### Done when

- Bus exists; behavior identical; REPORT + handoff; STOP
