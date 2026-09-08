# CuePlayer AI workflow

**Permanent engineering standard.** Every Cursor / cloud agent task in this
repository must follow this file end-to-end. Chat history is ephemeral; the
repo (especially `.ai/`) is the engineering history.

---

## 0. Mandatory loop (never skip)

```text
READ → PLAN (no code yet) → IMPLEMENT → REPORT + HANDOFF → UPDATE DOCS/NEXT → STOP
```

Never start the next queued task automatically.

---

## 1. Before implementation

### 1.1 Read (required)

1. `.ai/README.md`
2. `.ai/WORKFLOW.md` (this file)
3. `.ai/NEXT_TASK.md` — unless the **user message** explicitly overrides the task
4. `.ai/prompts/cursor_system.md` when starting fresh / no prior context
5. All docs named by the task, typically:
   - Feature → `docs/PRODUCT_SPEC.md` (relevant sections) + `AGENTS.md`
   - Architecture move → `docs/ARCHITECTURE_TARGET.md` + `docs/ARCHITECTURE_REVIEW.md` + **`docs/BOUNDARY_RULES.md`** + **`docs/MIGRATION_RULES.md`**
   - Packaging → `docs/DISTRIBUTION.md`
6. Latest `.ai/REPORT.md` and the newest file under `.ai/handoffs/` if continuing prior work

### 1.2 Plan (required — before any code or file edits)

Write a **short implementation plan** (in the agent turn / thinking) covering:

- Objective (one sentence)
- In scope / out of scope
- Files likely touched
- Risks (clock, `av_path_lock`, shared `Song`, persistence→ui, Remote private APIs)
- Test approach

**Do not start coding until that plan is complete.**

---

## 2. During implementation

| Type | Allowed | Forbidden |
|------|---------|-----------|
| **Feature** | User-requested behavior + tests | Drive-by architecture moves |
| **Bugfix** | Root cause + regression test when practical | “While here” refactors |
| **Architecture move** | Exactly **one** row from `ARCHITECTURE_TARGET.md`; shims OK | Behavior changes; multi-module moves |
| **Docs / AI infra** | `.ai/`, `docs/`, `AGENTS.md`, `.cursor/rules` | `src/cueplayer/` unless user asks |
| **Package** | Windows build instructions / scripts on Windows | Fake Windows EXE from Linux cloud |

### Architecture migration rules

From `docs/ARCHITECTURE_TARGET.md`:

- One module per PR / per focused agent task.
- Prefer `git mv` + **shim re-export** at the old path.
- No behavior change in a pure move PR.
- **`AudioEngine` sample position remains the only playback clock.**
- Target bans: `persistence → ui`, `remote → MainWindow` private `_` APIs.

### Fragile areas (touch only if the task requires)

- `media/av_lock.py` (`av_path_lock`) — Preview / mixer / scrub / waveforms
- Shared mutable `Song` across engine / video_sync / timeline / monitor / web_remote
- `persistence/project_store.py` → must import `domain.cue_list_columns` (never `ui`)

### Git

- Branches: `cursor/<descriptive-name>-028d` (lowercase).
- After allowed commits: push `origin` (see `.cursor/rules/auto-push.mdc`).
- No force-push to `master` / `main`.
- Windows employee builds: `packaging/build_windows.ps1` **on Windows only**.

### Tests

- Narrowest relevant pytest paths; UI often needs `QT_QPA_PLATFORM=offscreen`.
- Do not claim green without running tests for the touched area.

---

## 3. After implementation (required before stopping)

### 3.1 Update `.ai/REPORT.md`

Overwrite / refresh **latest report** with sections written for **ChatGPT review**:

1. **Task objective**
2. **What was implemented**
3. **Files changed**
4. **Architecture decisions**
5. **Tests performed**
6. **Remaining issues**
7. **Suggested next task**

### 3.2 Create a handoff archive file

Path: `.ai/handoffs/YYYY-MM-DD_<TaskName>.md`  
Same seven sections as `REPORT.md` (durable history; never delete old handoffs lightly).

Naming: use ASCII `TaskName` in `PascalCase` or `snake_case` (e.g. `2026-08-03_PermanentAiWorkflowStandard.md`).

### 3.3 Update outdated documentation

- `.ai/NEXT_TASK.md` → single next task (or blocked + reason)
- Any `docs/*` / `AGENTS.md` that the change made wrong
- Do **not** leave stale “current step” pointers

### 3.4 Commit, push, then **STOP**

- Commit + push the slice (including report + handoff).
- Update / open PR if in cloud-agent mode.
- **Stop immediately.** Never continue to the next architecture row or feature unless the user starts a new task.

### 3.5 ChatGPT paste block (required in the user-facing reply)

After every finished task, the agent’s **final user message** must include a
**single fenced plain-text block** the human can copy-paste to ChatGPT for
cross-tool review. The block must include at least:

- Project + branch + date
- Task objective / done summary
- Key files changed
- Architecture / product constraints that still apply
- Remaining issues
- Exact suggested next task (from `.ai/NEXT_TASK.md`)
- Pointers: `.ai/REPORT.md`, the new handoff path, relevant `docs/`

Do not omit this block. It is part of the permanent standard.

---

## 4. Communication

- User often uses **Traditional Chinese**; keep status replies concise.
- The repository — not chat — must be enough for the next session to continue.
- Never shrink P0 product scope without asking (`AGENTS.md`).
