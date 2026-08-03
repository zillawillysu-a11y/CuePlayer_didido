# Handoff — Sprint 1 Task 2: Transitional Layer Cleanup

**Date:** 2026-08-03  
**Branch:** `cursor/sprint1-transitional-cleanup-028d`  
**Type:** Cleanup (no behavior / no Service Layer)  
**Status:** Complete — STOP after REPORT

---

## Objective

Remove transitional compatibility layers; unify ports; preserve identical runtime behavior.

## Compatibility layers removed

1. `src/cueplayer/ui/cue_list_columns.py` (shim)
2. `src/cueplayer/playback/clock.py` (unused wall-clock)
3. `src/cueplayer/timeline/` + `src/cueplayer/ltc/` (empty stubs)
4. `MainWindow._AUDIO_SUFFIXES` alias

## Ports unified

- Canonical: `src/cueplayer/ports/*.py` (11 Protocol modules + `__init__`)
- Smoke: `tests/ports/test_ports_package.py`

## Call site retargets

- `ui/cue_monitor_panel.py` → `domain.cue_list_columns`
- Tests: `test_cue_list_columns.py`, `test_cue_list_global_ui.py`, `test_cue_list_column_order_load.py`

## Docs

- `docs/current_architecture.md` → ends with **READY FOR SERVICE LAYER**
- `CHANGELOG.md` created

## Remaining debt / risks

See `.ai/REPORT.md`.

## Recommendation for Task 3

Introduce `application/project_service` (open/save/dirty/autosave orchestration). No Repository. No RemoteHost yet (Task 4).

## Rollback

`git revert` this branch’s cleanup commit(s). To restore shim only: revive `ui/cue_list_columns.py` re-exports (not recommended).
