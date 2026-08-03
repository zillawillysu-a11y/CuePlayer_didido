# Next task

**Status:** Ready  
**Type:** Architecture move (foundation only — no behavior change)  
**Updated:** 2026-08-03  
**Workflow:** Mandatory `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP` (see `.ai/WORKFLOW.md`). Do not start this task in the same turn that only finished a different task.

---

## Current task

**`ARCHITECTURE_TARGET` step 0 — create empty `ports/` package**

### Goal

Add `src/cueplayer/ports/` with Protocol stubs only (no wiring, no call sites, no behavior change), as defined in [`docs/ARCHITECTURE_TARGET.md`](../docs/ARCHITECTURE_TARGET.md) migration table row **0**.

### In scope

- Create `src/cueplayer/ports/__init__.py`
- Add thin Protocol modules named in the target doc, for example:
  - `clock.py` → `PlaybackClock`
  - `remote_host.py` → `RemoteHost`
  - `project_store.py` → `ProjectStore`
  - (other port files listed in the target doc may be empty Protocol placeholders)
- Optional: one tiny import smoke test under `tests/` that imports `cueplayer.ports` only
- After done: update `.ai/REPORT.md`, add `.ai/handoffs/YYYY-MM-DD_PortsPackageStep0.md`, set this file to **step 1**, then **stop**

### Out of scope

- Implementing adapters or making `MainWindow` / `WebRemoteBridge` implement the ports
- Moving `cue_list_columns` (that is **step 1**)
- Refactoring `audio_engine.py`, timeline, mixer, or Remote auth
- Any feature work (multi-audio compare, Align Anchors, etc.)
- Packaging / version bumps

### Done when

- [ ] `python -c "import cueplayer.ports"` succeeds
- [ ] No production call sites depend on the new ports yet
- [ ] Existing tests still pass for untouched areas
- [ ] `.ai/REPORT.md` + handoff written; this file points at step **1**

### Read first

1. `.ai/README.md`, `.ai/WORKFLOW.md`, this file, `.ai/REPORT.md`
2. `docs/ARCHITECTURE_TARGET.md` (steps 0–1, shim technique)
3. `docs/ARCHITECTURE_REVIEW.md` (why ports matter — RemoteHost / Persistence→UI)
4. `AGENTS.md` (clock + layer non-negotiables)
5. Write a short plan **before** creating any files under `src/`

---

## Queue (do not start until current task is done)

| Order | Task | Doc anchor |
|------:|------|------------|
| 1 | Move `ui/cue_list_columns` → `domain/` + shims; stop `persistence → ui` | `ARCHITECTURE_TARGET` step 1 |
| 2 | `RemoteHost` protocol + bridge uses public host API only | step 2 |
| 3 | `application/autosave_service` extract | step 3 |
| … | Remaining rows 4–16 | `ARCHITECTURE_TARGET.md` |

## Product backlog (separate from architecture moves)

Only when the user asks for product work (not implied by architecture steps):

- Multi-audio version comparison + Align Anchors (`PRODUCT_SPEC` / `AGENTS.md`)
- Missing Media Relink polish
- MA Export Preview / naming polish
- NDI only after cue accuracy remains solid

## Notes for multi-machine handoff

- AI infra + this workflow standard: branch `cursor/ai-workflow-infra-028d` (merge when ready).
- Ship / package tip may live on a release branch; do not confuse packaging with architecture step 0.
- Engineering history: `.ai/REPORT.md` + `.ai/handoffs/` (not chat).
