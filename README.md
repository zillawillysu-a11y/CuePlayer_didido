# CuePlayer

Windows desktop timeline tool for lighting programmers.

Align multiple audio versions, LTC, VJ clips, and cue marks on one master timeline, then export Sequence / Timecode XML for grandMA2 and grandMA3.

## Status

Milestone 1 in progress: project skeleton, Unicode persistence, blank main window.

Product requirements: `docs/PRODUCT_SPEC.md`

## Requirements

- Windows 11
- Python 3.13+
- Git

## Setup

```powershell
cd C:\Users\willy\Projects\CuePlayer
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
```

## Run

```powershell
cueplayer
# or
python -m cueplayer.app
```

操作：
- `Space` Play / Pause（有音訊時會真的出聲）
- `1`–`9` 在目前 playhead 打點
- 左／右鍵微移 0.1 秒
- 點擊／拖曳時間軸 Seek
- 滾輪縮放時間軸
- **開啟音訊…** 載入 WAV/FLAC/OGG/MP3 等，主畫面顯示波形

## Test

```powershell
pytest
```

## Priority pain points

1. Multi-channel audio routing on Windows (not 2CH-only)
2. Full Chinese / Unicode path and filename support
3. Multiple VJ clips / loops with audio-master sync
4. Better multi-version media replace / relink for rehearsals
5. Optional native NDI later; cue accuracy and MA export come first

## MA export next step

At the company machine, export golden XML from grandMA2 3.9.61.5 and grandMA3 2.3.2.
Follow `docs/spikes/MA_GOLDEN_XML.md`, then place files under `fixtures/ma2/` and `fixtures/ma3/`.
