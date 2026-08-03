# CuePlayer — AI workflow

This directory is the **repo-local handoff** for Cursor / cloud agents.
Chat history does **not** travel between machines; `.ai/` + `docs/` + `AGENTS.md` do.

## What lives here

| Path | Purpose |
|------|---------|
| [`WORKFLOW.md`](WORKFLOW.md) | How agents must work on CuePlayer (read order, move rules, bans) |
| [`NEXT_TASK.md`](NEXT_TASK.md) | Single current next task (update after each finished module step) |
| [`prompts/cursor_system.md`](prompts/cursor_system.md) | Project system prompt for Cursor agents |

## Canonical product / architecture docs (do not duplicate)

| Doc | Role |
|-----|------|
| [`../AGENTS.md`](../AGENTS.md) | Non-negotiables, clock rule, GitHub sync |
| [`../docs/PRODUCT_SPEC.md`](../docs/PRODUCT_SPEC.md) | Product requirements (Unicode, routing, MA2/MA3, timeline) |
| [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) | Short intended layer diagram |
| [`../docs/ARCHITECTURE_REVIEW.md`](../docs/ARCHITECTURE_REVIEW.md) | As-built review (coupling, SRP, large files) |
| [`../docs/ARCHITECTURE_TARGET.md`](../docs/ARCHITECTURE_TARGET.md) | Strangler target: `ports/` / `application/` / `adapters/` |
| [`../docs/DISTRIBUTION.md`](../docs/DISTRIBUTION.md) | Windows packaging (`packaging/build_windows.ps1`) |

## Repo facts agents must know

- **Product:** Windows timeline tool for lighting programmers — multi-audio, LTC/MTC, VJ clips, marks → grandMA2/3 XML.
- **Package:** `src/cueplayer/` (Python / PySide6). Tests under `tests/`. Fixtures under `fixtures/`.
- **Clock:** `AudioEngine` sample position is the only playback clock; video Preview / Clean / NDI share one decode path.
- **Remote:** `origin` → `https://github.com/zillawillysu-a11y/CuePlayer_didido.git` (auto-push after commits; see `.cursor/rules/auto-push.mdc`).
- **Architecture debt:** UI-centric hub (`ui/main_window.py`); planned migration is **one module per PR**, behavior-preserving shims — see `ARCHITECTURE_TARGET.md`.

## Start every agent session

1. Read `.ai/NEXT_TASK.md` (what to do now).
2. Read `.ai/WORKFLOW.md` (how to do it).
3. Read `AGENTS.md` non-negotiables.
4. Open only the docs / files named by the current task.
5. Do **not** expand scope into refactor or unrelated features unless the user says so.
