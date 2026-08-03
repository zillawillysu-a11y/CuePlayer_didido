# Latest AI task report

**Date:** 2026-08-03  
**Branch:** `cursor/sprint1-project-service-028d`  
**Audience:** ChatGPT / future Cursor review

---

## Task objective

Sprint 1 · Task 3 — **Application Layer Foundation**: introduce
`application/project_service.py` for project lifecycle without changing runtime
behavior. No Repository. No playback/audio/timeline/UI redesign.

## What was implemented

- New `cueplayer.application.ProjectService` — new/open/save, dirty, autosave
  prefs, recent/last project, backup-before-overwrite helper.
- `MainWindow` holds a service instance; `_project_path` / `_dirty` proxy to it;
  file/autosave/session restore paths delegate I/O and prefs.
- Dialogs, media layout/bundle, engine stop, `_apply_project` remain in UI.
- Persistence functions unchanged.

## MainWindow before / after

| Responsibility | Before | After |
|----------------|--------|-------|
| Path + dirty flag | Local fields | `ProjectService` (property proxies) |
| New / open / save I/O | Inline `load_project`/`save_project` | Service methods |
| Autosave prefs + should-run | Inline QSettings | Service |
| Last / recent projects | Last path only in QSettings | Service (list + last key) |
| Dialogs / confirm | MainWindow | MainWindow (unchanged) |
| Media layout / bundle | MainWindow | MainWindow (unchanged) |
| Apply project to widgets/engine | MainWindow | MainWindow (unchanged) |

## Files modified

| Path | Change |
|------|--------|
| `src/cueplayer/application/__init__.py` | **New** package |
| `src/cueplayer/application/project_service.py` | **New** service |
| `src/cueplayer/ui/main_window.py` | Delegate lifecycle |
| `tests/application/test_project_service.py` | **New** unit tests |
| `docs/current_architecture.md` | Task 3 + READY FOR REPOSITORY LAYER |
| `CHANGELOG.md` | Unreleased note |
| `.ai/REPORT.md`, handoff, `NEXT_TASK.md` | Workflow |

## Architecture decisions

1. **Service owns state + prefs + thin I/O; UI owns dialogs/side effects** — preserves identical Save As / bundle / layout behavior.
2. **No Repository yet** — call `persistence.project_store` directly per task scope.
3. **Recent list seeded from legacy last-project** — restore path unchanged; list is additive for future UI.
4. **Property proxies for `_project_path` / `_dirty`** — minimize call-site churn and keep existing tests working.

## Tests

- Targeted: **26 passed** (application + autosave + session restore + new-project + persistence samples)
- Full suite: see handoff after run (expect same pre-existing failures as Task 2)

## Remaining technical debt

- No `ProjectStore` repository/adapter
- Song session / media jobs / RemoteHost still in MainWindow
- Pre-existing failing tests on Linux CI

## Risks

- Any code assuming `_project_path` is a plain attribute (e.g. `__dict__`) — none found in-repo
- Recent-list write is new QSettings key (additive; does not change restore)

## Suggested next task

Sprint 1 Task 4 — thin Repository / `ports.ProjectStore` adapter behind existing load/save functions.
