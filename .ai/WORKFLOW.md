# CuePlayer AI workflow

How Cursor / cloud agents must operate in this repository.

## 1. Read order (every task)

1. `.ai/NEXT_TASK.md` — the single active task.
2. This file — process constraints.
3. `AGENTS.md` — non-negotiables (Unicode, routing, MA export habits, clock).
4. Task-linked docs only, usually one of:
   - Feature work → `docs/PRODUCT_SPEC.md` (relevant section)
   - Architecture move → `docs/ARCHITECTURE_TARGET.md` + `docs/ARCHITECTURE_REVIEW.md`
   - Packaging → `docs/DISTRIBUTION.md`
5. `.ai/prompts/cursor_system.md` if starting a fresh agent without prior chat.

Do **not** re-read the entire codebase “just in case.” Scope to the module named in `NEXT_TASK.md`.

## 2. Task types

| Type | Allowed | Forbidden |
|------|---------|-----------|
| **Feature** | Product behavior the user asked for; tests; minimal docs if asked | Drive-by architecture moves |
| **Bugfix** | Root-cause fix + regression test when practical | “While here” refactors |
| **Architecture move** | Exactly one row from `ARCHITECTURE_TARGET.md` migration table; shims OK | Behavior changes, lock-strategy rewrites, multi-module moves |
| **Docs / AI infra** | `.ai/`, `docs/`, `AGENTS.md` | Changing `src/cueplayer/` unless explicitly requested |
| **Package** | Instruct / prepare Windows build; do not invent Linux Windows EXE | Claiming a cloud Linux agent produced a shippable `.exe` |

## 3. Architecture migration rules

From `docs/ARCHITECTURE_TARGET.md`:

- **One module per PR / per agent turn focus.**
- Prefer `git mv` + **shim re-export** at the old path so imports keep working.
- **No behavior change** in a move PR (no mixer window tuning, no Remote protocol changes, no BPM rewrite).
- **Clock stays in `AudioEngine`** — never add a second independent video/audio clock.
- Forbidden dependency directions (target): `persistence → ui`, `remote → MainWindow` private `_` APIs, `domain → media` (fix when that module’s turn comes).

Fragile areas (from review — touch only if the task requires):

- Global `media/av_lock.py` (`av_path_lock`) shared by Preview / mixer / scrub / waveforms
- Shared mutable `Song` across engine / video_sync / timeline / monitor / web_remote
- `persistence/project_store.py` importing `ui.cue_list_columns` (migration step 1)

## 4. Git / branches / PR

- Branch names: `cursor/<descriptive-name>-028d` (lowercase).
- After allowed commits: `git push -u origin HEAD` (see `.cursor/rules/auto-push.mdc`).
- Do not force-push `master` / `main`.
- Prefer ManagePullRequest / project PR tools over write `gh` for PR create/update when in cloud agent mode.
- Windows employee builds are produced **on Windows** via `packaging/build_windows.ps1`.

## 5. Testing expectations

- Run the narrowest relevant pytest paths for the touched package (`tests/domain`, `tests/playback`, `tests/ui`, …).
- UI tests often need `QT_QPA_PLATFORM=offscreen`.
- Do not claim “all green” without running tests for the area you changed.

## 6. Communication

- User often works in **Traditional Chinese**; keep status replies concise.
- Cursor chat is **per machine** — update `.ai/NEXT_TASK.md` when a migration step finishes so the other machine can continue.
- Never shrink P0 product scope without asking (`AGENTS.md`).

## 7. After finishing a task

1. Commit + push the slice.
2. Update `.ai/NEXT_TASK.md` to the **next** single step (or mark blocked with reason).
3. Stop. Do not start the next architecture row unless the user asks.
