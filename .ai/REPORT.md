# Latest AI task report

**Date:** 2026-08-03  
**Branch:** `cursor/architecture-guardrails-028d`  
**Audience:** ChatGPT / future Cursor review

---

## Task objective

Insert an **Architecture Guardrails** step before `ARCHITECTURE_TARGET` step 1:
publish permanent boundary and migration rule documents. No production module
migration and no `src/` changes.

## What was implemented

- Created `docs/BOUNDARY_RULES.md` — allowed/forbidden dependency directions, module boundaries, import examples (allowed/forbidden), rationale, shared runtime fences (`av_path_lock`, shared `Song`, frame sinks).
- Created `docs/MIGRATION_RULES.md` — one module per task, no behavior change, shim before replace, tests before removing old code, stop after each migration, REPORT + handoff required, procedure checklist.
- Cross-linked from `ARCHITECTURE.md`, `ARCHITECTURE_TARGET.md` (step **G**), `AGENTS.md`, `.ai/README.md`, `.ai/WORKFLOW.md`, `.ai/prompts/cursor_system.md`.
- Advanced `.ai/NEXT_TASK.md` to Step 1 with mandatory guardrails prerequisite.

## Files changed

| Path | Change |
|------|--------|
| `docs/BOUNDARY_RULES.md` | **New** permanent dependency rules |
| `docs/MIGRATION_RULES.md` | **New** permanent migration procedure |
| `docs/ARCHITECTURE.md` | Links to guardrails |
| `docs/ARCHITECTURE_TARGET.md` | Step G + links |
| `AGENTS.md` | Architecture section points at guardrails |
| `.ai/README.md` | Doc map |
| `.ai/WORKFLOW.md` | Architecture-move read list |
| `.ai/prompts/cursor_system.md` | Guardrails mention |
| `.ai/NEXT_TASK.md` | Step 1 + prerequisite |
| `.ai/REPORT.md` | This report |
| `.ai/handoffs/2026-08-03_ArchitectureGuardrails.md` | Archive |

## Architecture decisions

- Guardrails are **docs-only** and sit between ports step 0 and cue_list_columns step 1 so agents cannot migrate without an explicit fence.
- Boundary rules encode CuePlayer-specific forbidden edges (especially `persistence → ui`, `ports → adapters`, remote→MainWindow privates) rather than generic clean-architecture slogans.
- Migration rules bind to the existing `.ai` REPORT/handoff/stop loop so engineering history stays in-repo for ChatGPT review.
- No application behavior or import graph in `src/` was changed.

## Tests performed

- Documentation review only (no `src/` changes).
- No pytest required.

## Remaining issues

- Step 1 (`cue_list_columns` → domain) not started.
- As-built forbidden edges still exist in code until their migration steps run.
- `PRODUCT_SPEC.md` status header may still be stale vs shipped app (out of scope).

## Suggested next task

`.ai/NEXT_TASK.md`: **Step 1 — move `cue_list_columns` into domain + shims; persistence must not import ui.**  
Must read `BOUNDARY_RULES.md` + `MIGRATION_RULES.md` first. Then REPORT + handoff + stop.
