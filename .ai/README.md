# CuePlayer — AI workflow

This directory is the **repo-local engineering history** for Cursor / cloud agents.
Chat history does **not** travel between machines; `.ai/` + `docs/` + `AGENTS.md` do.

**Permanent standard:** every task must follow [`WORKFLOW.md`](WORKFLOW.md)
(`READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`).

## What lives here

| Path | Purpose |
|------|---------|
| [`WORKFLOW.md`](WORKFLOW.md) | Mandatory before/after process for every task |
| [`NEXT_TASK.md`](NEXT_TASK.md) | Single current next task |
| [`REPORT.md`](REPORT.md) | Latest task report (ChatGPT-reviewable) |
| [`handoffs/`](handoffs/) | Dated archive of completed tasks |
| [`prompts/cursor_system.md`](prompts/cursor_system.md) | Project system prompt |

## Canonical product / architecture docs (do not duplicate)

| Doc | Role |
|-----|------|
| [`../AGENTS.md`](../AGENTS.md) | Non-negotiables, clock rule, GitHub sync |
| [`../docs/PRODUCT_SPEC.md`](../docs/PRODUCT_SPEC.md) | Product requirements (Unicode, routing, MA2/MA3, timeline) |
| [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) | Short intended layer diagram |
| [`../docs/ARCHITECTURE_REVIEW.md`](../docs/ARCHITECTURE_REVIEW.md) | As-built review (coupling, SRP, large files) |
| [`../docs/ARCHITECTURE_TARGET.md`](../docs/ARCHITECTURE_TARGET.md) | Strangler target: `ports/` / `application/` / `adapters/` |
| [`../docs/BOUNDARY_RULES.md`](../docs/BOUNDARY_RULES.md) | **Permanent** allowed/forbidden dependency directions |
| [`../docs/MIGRATION_RULES.md`](../docs/MIGRATION_RULES.md) | **Permanent** one-module migration procedure |
| [`../docs/SPRINT_0_REVIEW.md`](../docs/SPRINT_0_REVIEW.md) | Sprint 0 retrospective (foundation complete) |
| [`../docs/DISTRIBUTION.md`](../docs/DISTRIBUTION.md) | Windows packaging (`packaging/build_windows.ps1`) |

## Repo facts agents must know

- **Product:** Windows timeline tool for lighting programmers — multi-audio, LTC/MTC, VJ clips, marks → grandMA2/3 XML.
- **Package:** `src/cueplayer/` (Python / PySide6). Tests under `tests/`. Fixtures under `fixtures/`.
- **Clock:** `AudioEngine` sample position is the only playback clock; video Preview / Clean / NDI share one decode path.
- **Remote:** `origin` → `https://github.com/zillawillysu-a11y/CuePlayer_didido.git` (auto-push after commits; see `.cursor/rules/auto-push.mdc`).
- **Architecture debt:** UI-centric hub (`ui/main_window.py`); planned migration is **one module per PR**, behavior-preserving shims — see `ARCHITECTURE_TARGET.md`.
- **Ports package (step 0 done):** `src/cueplayer/ports/` — Protocol interfaces only.
- **Step 1 done:** `cue_list_columns` lives in `domain/`; `ui.cue_list_columns` is a shim; persistence imports domain. Next: step 2 (`RemoteHost`).

## Start every agent session

1. Read `.ai/README.md` (this file), `.ai/WORKFLOW.md`, `.ai/NEXT_TASK.md`.
2. Read `.ai/REPORT.md` + latest `.ai/handoffs/*` if continuing work.
3. Read `AGENTS.md` non-negotiables + task-linked docs.
4. Write a short implementation **plan** — **no code until the plan is done**.
5. Implement only the active task; then write `REPORT.md` + a handoff file; update docs; **stop**.
