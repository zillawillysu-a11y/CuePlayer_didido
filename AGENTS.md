# CuePlayer — Agent Guide

Read `docs/PRODUCT_SPEC.md` before implementing features.

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

1. Skeleton + Unicode persistence tests + blank window — **done**
2. Audio / media routing spike (Focusrite / sounddevice) — **done**
3. MA2 / MA3 golden XML fixtures + exporters — **done**
4. Timeline UI, marks, video clips — **done (usable 1.0.4)**
5. UX polish + Mark Manager / NOW / Clean Output — **done (1.0.5)**
6. Follow-ups (not required to start using 1.0.5): multi-audio version compare + Align Anchors, Missing Media Relink, MA Export Preview / naming polish

## Architecture

UI / Domain / Playback Engine / Media / Exporters / Persistence stay separated.
Playback Engine is the only playback clock source.

## Multi-machine / GitHub

- Remote: `https://github.com/zillawillysu-a11y/CuePlayer_didido.git` (`origin`).
- After commits, push so laptop and desktop stay in sync (see `.cursor/rules/auto-push.mdc`).
- Cursor chat history is **per machine** and does not follow the repo; continue work from this guide + `docs/PRODUCT_SPEC.md` + recent commits.
- **Employee installs (no Git):** build on Windows with `packaging/build_windows.ps1` — see `docs/DISTRIBUTION.md`.

## Recent handoff (2026-08-01) — **1.0.5**

**Ship tip:** `cursor/release-1-0-5-028d` (integrate into `master` when ready)

```powershell
git fetch origin
git checkout cursor/release-1-0-5-028d
git pull
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

**Version:** `1.0.5` (`pyproject.toml` / `cueplayer.__version__` / Inno default).

**1.0.5 highlights (since 1.0.4):**
- View menu: Show Set List, Video/LTC tracks, Preview, Clean Output
- Single-line NOW (Primary + Secondary); Primary card can grow taller
- Mark Manager: Pause / Ask Note / Wave Note / Wave Cue; readable column widths
- Wave Label Size in Display Settings; mark RMB (Delete / Note / Cue ID / Type)
- Cue List & Set List Renumber confirmation
- Clean Output + setlist song-switch / long-video playback hardening

**Still open after 1.0.5 (next priorities when you ask):**
1. Multi-audio version comparison + Align Anchors
2. Missing Media Relink
3. MA Export Preview / Cue ID English-pinyin naming UI
4. LTC waveform display polish vs Reaper (when file is clean)
