# Handoff: Cue List columns → domain (Step 1)

**Date:** 2026-08-03  
**TaskName:** `CueListColumnsDomainMigrate`  
**Branch:** `cursor/cue-list-columns-domain-migrate-028d`  
**Audience:** ChatGPT / future Cursor review

---

## Task objective

Migrate `ui/cue_list_columns` → `domain/cue_list_columns` with UI shim and
persistence retarget; no behavior change.

## What was implemented

- Domain module (moved), UI shim, persistence→domain, tests/docs updates.

## Files changed

See `.ai/REPORT.md` table.

## Architecture decisions

- Clear forbidden `persistence → ui`; keep ui import path via shim for callers.
- Domain remains Qt-free leaf.

## Tests performed

23 passed (`test_cue_list_columns`, `test_cue_list_column_order_load`, `test_cue_list_global_ui`).

## Remaining issues

- Shim retained; Step 2 RemoteHost not started.

## Suggested next task

ARCHITECTURE_TARGET step 2 — `RemoteHost` for Web Remote.

## Migration Checklist

- [x] Old tests pass
- [x] Public API unchanged
- [x] Shim verified
- [x] Dependency direction improved
- [x] No behavior changes

## Rollback Plan

1. `git revert` the Step 1 migrate commit (preferred), **or** restore full
   `ui/cue_list_columns.py` from pre-migrate SHA and remove
   `domain/cue_list_columns.py`.
2. Point `project_store` back at `cueplayer.ui.cue_list_columns`.
3. Restore pre-migrate column tests (ui import sentinel).
4. Revert step-1 ✅ doc markers.
5. Re-run the three pytest modules listed in REPORT.
