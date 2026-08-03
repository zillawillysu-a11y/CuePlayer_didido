# Next task

**Status:** Ready  
**Type:** Architecture move (behavior-preserving shim)  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Cue List columns **safety net** complete — see `.ai/REPORT.md` and
`.ai/handoffs/2026-08-03_CueListColumnsSafetyNet.md`.

**Prerequisite (mandatory):** `docs/BOUNDARY_RULES.md` + `docs/MIGRATION_RULES.md`

---

## Current task

**`ARCHITECTURE_TARGET` step 1 — move `cue_list_columns` into domain**

### Goal

Move `ui/cue_list_columns` → `domain/cue_list_columns`, leave shims so existing
imports keep working, and stop `persistence` from importing `ui.*`.

### In scope

- `git mv` / relocate into `domain/`
- Shim at old `ui.cue_list_columns` path
- Update `persistence.project_store` to import from domain
- Keep all safety-net tests green (same assertions)
- REPORT + handoff + next → step **2**; **stop**

### Out of scope

- Behavior changes to normalize/constants
- RemoteHost (step 2)
- Deleting the ui shim in the same PR without proving callers updated

### Read first

1. `.ai/WORKFLOW.md`, this file, `.ai/REPORT.md`, safety-net handoff
2. `BOUNDARY_RULES.md` + `MIGRATION_RULES.md`
3. `tests/ui/test_cue_list_columns.py` + `tests/persistence/test_cue_list_column_order_load.py`

---

## Queue

| Order | Task | Anchor |
|------:|------|--------|
| 2 | RemoteHost + bridge public API | step 2 |
| 3+ | application services / adapter moves | `ARCHITECTURE_TARGET.md` |
