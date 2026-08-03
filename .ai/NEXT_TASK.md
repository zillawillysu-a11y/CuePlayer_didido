# Next task

**Status:** Queued — awaiting human start  
**Type:** Architecture / Playback events on EventBus  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 3 Task 3 — Event Bus Foundation  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint3EventBusFoundation.md`  
Baseline: `docs/current_architecture.md` (ends READY FOR PLAYBACK EVENTS)

---

## Current task

### Sprint 3 — Task 4: Playback events

**Do not auto-start until the user explicitly continues.**

### Goal

First EventBus adoption for a **narrow** set of playback-related events
(chrome / playing-changed style). Do **not** put continuous playhead ticks
on the bus. `AudioEngine` remains the sole sample clock.

### Read first

1. `docs/current_architecture.md`
2. `docs/BOUNDARY_RULES.md` + `docs/MIGRATION_RULES.md`
3. `core/event_bus.py`
4. `application/playback_service.py`

### In scope

- Small event types + publish from PlaybackService (or thin adapter)
- Optional one UI subscriber path
- Tests + docs

### Out of scope

- Position/frame clock on the bus
- ShowSession / Project / Settings migration
- Replacing all Qt signals

### Done when

- At least one playback-related event published via EventBus without
  changing clock semantics; REPORT + handoff; STOP
