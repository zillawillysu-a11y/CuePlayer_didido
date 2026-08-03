# Next task

**Status:** Queued — awaiting human start  
**Type:** Architecture / Settings service  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 2 Task 5 — Playback Foundation  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint2PlaybackFoundation.md`  
Baseline: `docs/current_architecture.md` (ends READY FOR SETTINGS SERVICE)

---

## Current task

### Sprint 2 — Task 6: Settings service foundation

**Do not auto-start until the user explicitly continues.**

### Goal

Introduce `application/settings_service.py` for machine-global / shared settings
orchestration currently scattered across MainWindow and `persistence.audio_prefs`,
without changing preference schemas or UI behavior.

### Read first

1. `docs/current_architecture.md` (§14 settings flow, plan Task 6)
2. `docs/BOUNDARY_RULES.md` + `docs/MIGRATION_RULES.md`
3. `persistence/audio_prefs.py`, ProjectService autosave keys

### In scope

- Settings service façade
- Wire high-value call sites (audio prefs / apply-to-project) if safe
- Tests

### Out of scope

- Redesigning QSettings keys, RemoteHost, AudioEngine, Timeline

### Done when

- Service exists; behavior identical; REPORT + handoff; STOP
