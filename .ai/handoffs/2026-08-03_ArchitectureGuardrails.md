# Handoff: Architecture Guardrails

**Date:** 2026-08-03  
**TaskName:** `ArchitectureGuardrails`  
**Branch:** `cursor/architecture-guardrails-028d`  
**Audience:** ChatGPT / future Cursor review

---

## Task objective

Insert Architecture Guardrails **before** Step 1: permanent
`BOUNDARY_RULES.md` + `MIGRATION_RULES.md`. No production migration.

## What was implemented

- `docs/BOUNDARY_RULES.md` — dependency directions, boundaries, import examples, rationale.
- `docs/MIGRATION_RULES.md` — one-module strangler procedure tied to REPORT/handoff/stop.
- Cross-links from architecture docs, AGENTS, and `.ai` workflow files.
- `NEXT_TASK` set to Step 1 with mandatory guardrails read.

## Files changed

See `.ai/REPORT.md` table (docs + `.ai` only; **no `src/`**).

## Architecture decisions

- Guardrails are permanent repo law for all later moves.
- Placed after ports (step 0) and before first production relocate (step 1).
- Complements — does not replace — `ARCHITECTURE_TARGET.md` ordering.

## Tests performed

- Docs-only; no pytest.

## Remaining issues

- Step 1 not started; forbidden edges remain in as-built code until migrated.

## Suggested next task

**Step 1 — `cue_list_columns` → domain + shims** (after reading both guardrails docs).
