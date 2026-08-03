# CuePlayer Migration Rules

**Status:** Permanent architecture rule  
**Audience:** Humans + Cursor / ChatGPT agents  
**Related:** [`BOUNDARY_RULES.md`](BOUNDARY_RULES.md) · [`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md) · [`ARCHITECTURE_REVIEW.md`](ARCHITECTURE_REVIEW.md) · [`../.ai/WORKFLOW.md`](../.ai/WORKFLOW.md)

This is the **only** approved way to move CuePlayer toward
`ports/` + `application/` + `adapters/`. It is a strangler strategy — not a rewrite.

---

## 1. Goals

- Keep **all current product behavior** working on every merge.
- Move **one module (or one clear seam) per task / PR**.
- Leave the repo understandable without chat history (`.ai/REPORT.md` + handoffs).

Non-goals for migration PRs: features, lock-strategy experiments, BPM rewrites,
Remote protocol redesign, packaging.

---

## 2. Permanent strategy (checklist)

| # | Rule | Detail |
|---|------|--------|
| 1 | **One module per task** | Exactly one row from `ARCHITECTURE_TARGET.md` (or one explicitly approved seam). No “while here” second moves. |
| 2 | **No behavior changes** | Prefer `git mv` + re-exports. Do not retune mixer windows, Remote auth, LTC detect, or UI timing in a move PR. |
| 3 | **Shim before replacement** | Keep the **old import path** working via shim (`from new_path import *` / explicit re-exports) until callers are updated in a later task. |
| 4 | **Tests before removing old code** | Run the narrowest relevant tests **before** deleting a shim or old module. If tests are missing for that seam, add a minimal smoke/regression first. |
| 5 | **Stop after every migration** | After REPORT + handoff + `NEXT_TASK` update: **stop**. Never auto-start the next architecture row. |
| 6 | **REPORT + handoff every time** | Update `.ai/REPORT.md` and add `.ai/handoffs/YYYY-MM-DD_<TaskName>.md`. Final user reply includes a ChatGPT paste block (`.ai/WORKFLOW.md` §3.5). |
| 7 | **Respect boundary rules** | Each move must remove or avoid edges banned in [`BOUNDARY_RULES.md`](BOUNDARY_RULES.md). Do not introduce new forbidden imports. |
| 8 | **Clock stays put** | Do not create a second playback clock. `AudioEngine` / `PlaybackClock` remains master. |

---

## 3. Standard move procedure

```text
1. Read NEXT_TASK + BOUNDARY_RULES + this file + the target step in ARCHITECTURE_TARGET
2. Write a short plan (scope, old path, new path, shim, tests) — no code until planned
3. Create branch cursor/<name>-028d
4. git mv (or add new + shim old) for exactly one module/seam
5. Fix imports only as required for that module (prefer shims over mass rewrites)
6. Run targeted pytest
7. Update ARCHITECTURE_TARGET step status if applicable
8. Write .ai/REPORT.md + handoff; set NEXT_TASK to the following single step
9. Commit, push, PR
10. STOP
```

### Shim pattern

```python
# old_path.py  (temporary)
"""Shim — use cueplayer.<new_path> instead."""
from cueplayer.<new_path> import *  # noqa: F403
from cueplayer.<new_path> import __all__  # if defined
```

Delete the shim only in a **later** task after grep shows no remaining callers
(or callers were updated) **and** tests still pass.

---

## 4. What counts as “one module”

Allowed as a single task:

- One package relocate (e.g. `playback/` → `adapters/playback/` + top-level shim)
- One leaf module move (e.g. `ui/cue_list_columns` → `domain/cue_list_columns` + shim)
- One interface adoption step (e.g. bridge talks to `RemoteHost` only) **without** relocating unrelated packages

Not allowed in the same task:

- Move + feature
- Move + behavior fix unrelated to import breakage
- Two `ARCHITECTURE_TARGET` rows
- “Clean up MainWindow” while moving a leaf

---

## 5. Testing expectations for migrations

- Always run tests that cover the moved seam (e.g. `tests/ui/test_cue_list_columns.py`, package import smokes).
- If the move only adds shims, at minimum: import old path + new path + existing unit tests for that helper.
- UI tests: `QT_QPA_PLATFORM=offscreen` when needed.
- Do not delete shims on red tests.

---

## 6. Documentation obligations

Every migration task must:

1. Refresh `.ai/REPORT.md` (seven sections).
2. Add `.ai/handoffs/YYYY-MM-DD_<TaskName>.md`.
3. Update `.ai/NEXT_TASK.md` to the **next** single step only.
4. Update `ARCHITECTURE_TARGET.md` step table if a numbered step completed.
5. Emit the ChatGPT copy-paste block in the user-facing finale.

Optional but encouraged: note cleared forbidden edges in the report
(“persistence no longer imports ui”).

---

## 7. Ordered backlog pointer

Canonical order remains [`ARCHITECTURE_TARGET.md`](ARCHITECTURE_TARGET.md):

| Step | Summary |
|-----:|---------|
| 0 | ✅ `ports/` Protocols |
| **Guardrails** | ✅ This file + `BOUNDARY_RULES.md` (docs only; inserted before step 1) |
| 1 | `cue_list_columns` → domain + shims |
| 2 | `RemoteHost` adoption for Web Remote |
| 3+ | application services, adapter package moves, … |

Do not skip guardrails awareness: **Step 1 and every later migration must comply with both rule docs.**

---

## 8. Failure modes (do not repeat)

- Mid-demux unlock / lock thrash “fixes” smuggled into a relocate PR
- Deleting shims in the same PR that moved the module
- Continuing to step N+1 in the same agent turn
- Expanding `RemoteHost` with private MainWindow passthroughs that re-create coupling
- Claiming Windows packaging from a Linux agent

---

## 9. One-sentence rule

**Move one seam, keep behavior identical, shim the old path, prove with tests, record history in `.ai/`, then stop.**
