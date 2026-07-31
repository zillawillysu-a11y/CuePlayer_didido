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
5. Follow-ups (not required to start using 1.0.4): multi-audio version compare + Align Anchors, Missing Media Relink, MA Export Preview / naming polish

## Architecture

UI / Domain / Playback Engine / Media / Exporters / Persistence stay separated.
Playback Engine is the only playback clock source.

## Multi-machine / GitHub

- Remote: `https://github.com/zillawillysu-a11y/CuePlayer_didido.git` (`origin`).
- After commits, push so laptop and desktop stay in sync (see `.cursor/rules/auto-push.mdc`).
- Cursor chat history is **per machine** and does not follow the repo; continue work from this guide + `docs/PRODUCT_SPEC.md` + recent commits.
- **Employee installs (no Git):** build on Windows with `packaging/build_windows.ps1` — see `docs/DISTRIBUTION.md`.

## Recent handoff (2026-07-31) — **1.0.4 / first milestone usable**

**Ship tip:** `cursor/release-1-0-4-028d` (integrate into `master` when ready)

```powershell
git fetch origin
git checkout cursor/release-1-0-4-028d
git pull
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

**Version:** `1.0.4` (`pyproject.toml` / `cueplayer.__version__` / Inno default).

**Milestone 1 status:** Core show workflow is usable — setlist, timeline (Music → Video → LTC → Marks), marks 1–9, sample-locked video, Clean Output + NDI, LTC/MTC, MA2/MA3 export, compact UI polish.

**Included since 1.0.3 (high level):**
- Narrow-window clipping fixes (transport A/B, NOW cards, TC status, Setlist footer, splitters)
- NOW collapse when both displays off; restore via Cue List / clock context menu
- Cue List playhead follow without locking outer Timecode scroll
- Hidden Mark tracks ignore digit shortcuts (4–9 off when tracks hidden)

**Still open after 1.0.4 (next priorities when you ask):**
1. Multi-audio version comparison + Align Anchors
2. Missing Media Relink
3. MA Export Preview / Cue ID English-pinyin naming UI
4. LTC waveform display polish vs Reaper (when file is clean)
