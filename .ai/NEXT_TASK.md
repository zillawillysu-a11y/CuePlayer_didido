# Next task

**Status:** Ready  
**Type:** Architecture move  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Step 1 `cue_list_columns` → domain + shim — see `.ai/REPORT.md` and
`.ai/handoffs/2026-08-03_CueListColumnsDomainMigrate.md`.

**Prerequisite:** `docs/BOUNDARY_RULES.md` + `docs/MIGRATION_RULES.md`

---

## Current task

**`ARCHITECTURE_TARGET` step 2 — `RemoteHost` + bridge public API only**

### Goal

Adopt `ports.RemoteHost` so Web Remote talks only to a public host surface —
no MainWindow private `_` attribute access.

### In scope

- Ensure `ports.RemoteHost` is available on this line (merge ports step 0 if needed)
- Thin public host adapter / MainWindow conformance
- Bridge uses RemoteHost only
- Tests + REPORT + handoff; NEXT → step 3; **stop**

### Out of scope

- Moving web_remote package to adapters/
- New Remote features
- Deleting `ui.cue_list_columns` shim

### Read first

1. Safety/migrate handoffs for columns (done)
2. `BOUNDARY_RULES.md` (remote → MainWindow privates ban)
3. `ports/remote_host.py` / `ARCHITECTURE_TARGET` step 2
