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
- **Employee installs (no Git):** build on Windows with `packaging/build_windows.ps1` — see `docs/DISTRIBUTION.md`.

## Recent handoff (2026-07-28)

**Laptop tip branch (latest):** `cursor/setlist-sheet-cue-id-028d`

```powershell
git fetch origin
git checkout cursor/setlist-sheet-cue-id-028d
git pull
pip install -e ".[dev,midi]"
python -m cueplayer.app
```

**Shipped today (PR stack, not all merged to master yet):**
- Set List Sheet: 曲序/曲名/英文名/**Seq/Cue ID**/TC/BPM/Note、Folder 分隔、欄寬可拖、曲序可改
- 左邊 Setlist 欄寬可拖
- Video+LTC 眼睛固定在 Music、整場全域開/關
- 時間軸順序：**Music → Video → LTC → Marks**（拉開高度可把 Marks 往下擠）
- 深色啟動 Splash（避免大白）

**Asked today but NOT done yet:**
1. LTC 畫波形：有些歌 Reaper 乾淨、CuePlayer 仍毛（檔案本身髒的除外）— 尚未對齊 Reaper 顯示
2. MA Export Preview／命名策略 UI（規格裡的 Cue ID 自動翻譯／拼音選項）— 尚未做
3. 上述 PR 尚未全部 merge 進 `master`（筆電請先 checkout tip 分支）

Older still-open: multi-audio version compare + Align Anchors, Missing Media Relink, MA Export Preview/Validation; NDI only after cue accuracy is solid.

