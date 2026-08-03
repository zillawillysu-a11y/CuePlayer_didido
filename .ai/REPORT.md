# Latest AI task report

**Date:** 2026-08-03  
**Branch:** `cursor/cue-list-columns-domain-migrate-028d`  
**Audience:** ChatGPT / future Cursor review

---

## Task objective

Execute **ARCHITECTURE_TARGET Step 1**: migrate `ui/cue_list_columns` into
`domain/` with a UI shim and retarget persistence to domain, preserving 100%
behavior and public API.

## What was implemented

- `git mv` → `src/cueplayer/domain/cue_list_columns.py` (same logic; domain docstring).
- `src/cueplayer/ui/cue_list_columns.py` became an explicit shim re-exporting all public symbols (`__all__`).
- `persistence/project_store.py` imports `normalize_cue_list_column_order` from **domain** (not ui).
- Tests: flipped persistence→ui sentinel; added shim identity + domain API checks.
- Docs: ARCHITECTURE_TARGET step 1 ✅; BOUNDARY_RULES note cleared edge; MIGRATION_RULES backlog.

## Files changed

| Path | Change |
|------|--------|
| `src/cueplayer/domain/cue_list_columns.py` | **New home** (moved) |
| `src/cueplayer/ui/cue_list_columns.py` | Shim re-export |
| `src/cueplayer/persistence/project_store.py` | Import domain |
| `tests/ui/test_cue_list_columns.py` | Migration assertions |
| `docs/ARCHITECTURE_TARGET.md` | Step 1 done |
| `docs/BOUNDARY_RULES.md` | Edge cleared note |
| `docs/MIGRATION_RULES.md` | Backlog ✅ |
| `.ai/NEXT_TASK.md` | Step 2 |
| `.ai/REPORT.md` | This report |
| `.ai/handoffs/2026-08-03_CueListColumnsDomainMigrate.md` | Archive |

## Architecture decisions

- Domain owns the Qt-free helper; UI path remains for `cue_monitor_panel` and tests via shim (no mass import rewrite required this step).
- Persistence→domain is an **allowed** adapter→domain edge; removes forbidden persistence→ui.
- No new dependency directions introduced (ui→domain via shim is fine; domain still has no ui/persistence imports).

## Tests performed

- `pytest tests/ui/test_cue_list_columns.py tests/persistence/test_cue_list_column_order_load.py tests/ui/test_cue_list_global_ui.py` → **23 passed**

## Remaining issues

- `ui.cue_list_columns` shim still present (intentional; delete in a later task after callers optionally switch).
- `cue_monitor_panel` still imports the ui shim path (OK).
- Step 2 (`RemoteHost`) not started; ports package may need merge onto this release line if missing.

## Suggested next task

Step 2: Web Remote uses `ports.RemoteHost` only (no MainWindow private `_` access).

## Migration Checklist

- [x] Old tests pass (safety-net + global UI + persistence load)
- [x] Public API unchanged (same symbol names/values via shim `is` identity)
- [x] Shim verified (`test_ui_shim_reexports_identical_objects`)
- [x] Dependency direction improved (`persistence` → `domain`, not `ui`)
- [x] No behavior changes (normalize logic byte-identical aside from docstring)

## Rollback Plan

If this migration must be reverted:

1. On this branch (or a revert PR): restore `src/cueplayer/ui/cue_list_columns.py` to the full implementation from pre-migrate commit (`d30a8ba` / parent before migrate), **or** `git revert` the Step 1 commit.
2. Delete `src/cueplayer/domain/cue_list_columns.py` if reverting via file restore.
3. Change `project_store.py` import back to:
   `from cueplayer.ui.cue_list_columns import normalize_cue_list_column_order`
4. Restore `tests/ui/test_cue_list_columns.py` sentinel
   `test_project_store_currently_imports_normalize_from_ui` (remove domain/shim-only tests if needed).
5. Revert docs step-1 ✅ markers in `ARCHITECTURE_TARGET.md` / `BOUNDARY_RULES.md` / `MIGRATION_RULES.md`.
6. Run:
   `pytest tests/ui/test_cue_list_columns.py tests/persistence/test_cue_list_column_order_load.py tests/ui/test_cue_list_global_ui.py`
7. Prefer `git revert <step1_sha>` as the single clean rollback when the migrate is one commit.
