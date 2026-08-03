# Latest AI task report

**Date:** 2026-08-03  
**Branch:** `cursor/cue-list-columns-safety-net-028d` (from release tip + architecture docs overlay)  
**Audience:** ChatGPT / future Cursor review

---

## Task objective

Build a **migration safety net** for `ui/cue_list_columns` before Step 1 relocate:
review implementation, expand automated tests without changing behavior, map
dependencies, and document migration risks. **Do not move the module.**

## What was implemented

- Reviewed `src/cueplayer/ui/cue_list_columns.py` (pure constants + `normalize_cue_list_column_order`; Qt-free).
- Expanded `tests/ui/test_cue_list_columns.py` (constants, labels, logical indices, normalize edge cases, idempotence, Qt-free source guard, persistence→ui import sentinel).
- Added `tests/persistence/test_cue_list_column_order_load.py` (load_project normalizes dirty/missing `cue_list_column_order`, including Unicode project/song names).
- Documented dependency graph + risks in this report and the handoff.
- Marked step **1S** in `ARCHITECTURE_TARGET.md` / `MIGRATION_RULES.md`; `NEXT_TASK` → real Step 1 migrate.

## Files changed

| Path | Change |
|------|--------|
| `tests/ui/test_cue_list_columns.py` | Expanded behavior lock (no prod edits) |
| `tests/persistence/test_cue_list_column_order_load.py` | **New** load-path normalize tests |
| `docs/ARCHITECTURE_TARGET.md` | Step **1S** safety net |
| `docs/MIGRATION_RULES.md` | Note 1S |
| `.ai/NEXT_TASK.md` | Points at Step 1 migrate |
| `.ai/REPORT.md` | This report |
| `.ai/handoffs/2026-08-03_CueListColumnsSafetyNet.md` | Archive |
| `.ai/` + architecture docs | Brought onto release-based branch for continuity |

**Unchanged production module:** `src/cueplayer/ui/cue_list_columns.py`

## Architecture decisions

- Safety net runs on **release tip** (where the module exists). Older architecture-only tips lacked this file.
- Pure-function tests are the primary lock; persistence load tests lock the **forbidden** `persistence → ui` call site behavior consumers rely on.
- UI header drag/reorder in `CueMonitorPanel` is integration-heavy; existing `test_cue_list_global_ui.py` covers Interactive/movable header via `LOGICAL_INDEX_BY_FIELD`. Not duplicated here — see risks.
- Sentinel test that `project_store` imports from `ui` is intentional: it must **flip** after Step 1 (update that assertion when migrating).

## Tests performed

- `pytest tests/ui/test_cue_list_columns.py tests/persistence/test_cue_list_column_order_load.py` → **15 passed**

## Remaining issues / migration risks

See handoff for full graph. Highlights:

1. **Forbidden edge:** `persistence.project_store` imports `ui.cue_list_columns` — Step 1 must retarget to domain + keep load normalize identical.
2. **Wide UI consumer:** `cue_monitor_panel.py` imports all symbols; shim must re-export everything (`CUE_LIST_FIELDS`, labels, logical map, normalize, defaults).
3. **Prefs / header state:** column order also flows through monitor UI prefs + header restore; moving the helper must not change normalize results used after drag-reorder.
4. **Sentinel test update required** in Step 1 (`test_project_store_currently_imports_normalize_from_ui`).
5. Architecture stack PRs (ports/guardrails) and this release-based safety net need careful merge order.

## Suggested next task

**Step 1 migrate:** `ui/cue_list_columns` → `domain/cue_list_columns` + ui shim; persistence imports domain; all safety-net tests green (adjust import sentinel); REPORT + handoff + stop.
