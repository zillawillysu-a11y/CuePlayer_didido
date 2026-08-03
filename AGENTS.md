# CuePlayer — Agent Guide

Read `docs/PRODUCT_SPEC.md` before implementing features.

**AI workflow (permanent):** [`.ai/README.md`](.ai/README.md) → [`.ai/WORKFLOW.md`](.ai/WORKFLOW.md) → [`.ai/NEXT_TASK.md`](.ai/NEXT_TASK.md).  
Every task: **plan before code**; after code update [`.ai/REPORT.md`](.ai/REPORT.md) + a file under [`.ai/handoffs/`](.ai/handoffs/); then **stop**.  
System prompt: [`.ai/prompts/cursor_system.md`](.ai/prompts/cursor_system.md). Cursor rule: `.cursor/rules/ai-workflow.mdc`.

## Non-negotiables

- Full Unicode / Chinese support for project names, folders, and media paths from day one.
- Multi-audio version comparison (not replace-only).
- One audio output device with free multi-channel routing.
- Do not assume LTC is always Left or Right.
- Video clips share the audio sample clock; no second independent video player for OBS/NDI output.
- Main marks export as Go+ with explicit CueDestination (user habit; not bare Go+, not Goto-by-default); Top Button marks reuse one 2-cue self-release sequence.
- MA2 full export should include a Plugin that assigns sequences to executors before Timecode import.
- MA3 full export should include a Macro that imports sequences, assigns executors, then imports Timecode.
- Support timecode-only re-export after executors are already assigned.
- Never write Chinese into MA XML labels; keep Display Name and MA Export Name separate.
- Do not shrink P0 scope without asking the user.

## Milestone order

1. Skeleton + Unicode persistence tests + blank window
2. Audio / media routing spike (Focusrite / sounddevice)
3. MA2 / MA3 golden XML fixtures + exporters
4. Timeline UI, marks, video clips
5. Optional NDI (only after cue accuracy is solid)

## Architecture

UI / Domain / Playback Engine / Media / Exporters / Persistence stay separated.
Playback Engine is the only playback clock source.

## Multi-machine / GitHub

- Remote: `https://github.com/zillawillysu-a11y/CuePlayer_didido.git` (`origin`).
- After commits, push so laptop and desktop stay in sync (see `.cursor/rules/auto-push.mdc`).
- Cursor chat history is **per machine** and does not follow the repo; continue work from this guide + `docs/PRODUCT_SPEC.md` + recent commits.

## Recent handoff (2026-07)

Shipped on `master`: timeline UI, marks, sample-locked video clips (waveforms, Clean Output, still images, loop, crossfade), device-aware audio (WASAPI defaults, resample), LTC/MTC, MA export refinements. Deferred: setlist/timeline/export selection row colors. Next milestone item often: polish video/alignment UX or NDI only after cue accuracy is solid.
