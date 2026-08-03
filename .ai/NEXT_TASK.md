# Next task

**Status:** Queued — awaiting human start  
**Type:** Architecture / git tip unify  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 1 Task 1 — Architecture Assessment  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint1ArchitectureAssessment.md`  
Baseline: `docs/current_architecture.md`

---

## Current task

### Sprint 1 — Task 2: Unify foundation tip (`ports/` + columns migrate)

**Do not auto-start until the user explicitly continues.**

### Goal

One trunk tip that has **both**:

1. Importable `cueplayer.ports` (Protocol sources from architecture Step 0)
2. Sprint 0 columns migrate (`domain.cue_list_columns` + UI shim + tests)

### Read first

1. `docs/current_architecture.md` (esp. §4, §15 P0, Sprint 1 plan Task 2)
2. `docs/BOUNDARY_RULES.md` + `docs/MIGRATION_RULES.md`
3. `docs/SPRINT_0_REVIEW.md` §3 / §8 / §10
4. Branch with ports sources: `origin/cursor/ports-package-step0-028d` (and guardrails parents as needed)

### In scope

- Git integrate / cherry-pick / merge so ports `.py` files exist on the working tip
- Confirm smoke: `import cueplayer.ports` + existing columns / ports tests
- Docs touch-ups only if required for accuracy

### Out of scope

- RemoteHost wiring (Task 3)
- Shim deletion / application package (Task 4)
- Feature work, adapters renames, behavior changes

### Done when

- `src/cueplayer/ports/*.py` present and importable
- Columns domain + shim still green
- REPORT + handoff updated; STOP
