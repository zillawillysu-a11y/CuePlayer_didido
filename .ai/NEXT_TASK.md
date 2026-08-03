# Next task

**Status:** Ready  
**Type:** Architecture move (behavior-preserving shim)  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Step 0 `ports/` Protocols shipped — see `.ai/REPORT.md` and
`.ai/handoffs/2026-08-03_PortsPackageStep0.md`.

---

## Current task

**`ARCHITECTURE_TARGET` step 1 — move `cue_list_columns` into domain**

### Goal

Move `ui/cue_list_columns` → `domain/cue_list_columns` (or equivalent), leave
shims so existing imports keep working, and stop `persistence` from importing
`ui.*`.

### In scope

- `git mv` / relocate column-order helpers into `domain/`
- Shim at old `ui.cue_list_columns` path
- Update `persistence.project_store` to import from domain (not ui)
- Tests for normalize/order helpers still green
- REPORT + handoff + set next to step **2**; **stop**

### Out of scope

- Wiring `ports.RemoteHost` (step 2)
- Refactors of MainWindow / exporters / playback
- Behavior changes to column defaults

### Read first

1. `.ai/WORKFLOW.md`, this file, `.ai/REPORT.md`
2. `docs/ARCHITECTURE_TARGET.md` step 1
3. `docs/ARCHITECTURE_REVIEW.md` (persistence → ui leak)
4. Plan before edits

---

## Queue

| Order | Task | Anchor |
|------:|------|--------|
| 2 | RemoteHost + bridge public API | step 2 |
| 3 | autosave_service | step 3 |
| … | 4–16 | `ARCHITECTURE_TARGET.md` |
