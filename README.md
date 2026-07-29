# CuePlayer

Windows desktop timeline tool for lighting programmers.

Align multiple audio versions, LTC, VJ clips, and cue marks on one master timeline, then export Sequence / Timecode XML for grandMA2 and grandMA3.

## Status

Core P0 timeline / marks / video / MA2·MA3 export are on `master`.

Laptop all-in-one branch: `cursor/laptop-ux-pack-028d`
(Auto Save, LTC 2ch clamp, setlist audio drop, hide Video track, Add Song Browse, New Project confirm, MIDI via Windows winmm / optional pygame-ce).

Latest UX fixes (video drag, Explorer drop, decode perf, Video Preview under timeline): `cursor/video-drag-drop-perf-028d`

Product requirements: `docs/PRODUCT_SPEC.md`  
User tips (shortcuts / Bundle / Relink): `docs/USER_MANUAL.md`  
Agent handoff: `AGENTS.md`

## Requirements

- Windows 11
- Python 3.13+ (3.14 OK)
- Git

## Update + run (this laptop)

```powershell
cd C:\Users\User\Projects\CuePlayer_didido
git fetch origin
git checkout cursor/laptop-ux-pack-028d
git pull

.\.venv\Scripts\python.exe -m pip install -U pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
# Do NOT install pygame on 3.14 (no wheel / build fails).
# Windows MTC uses winmm.dll with no extra package.
# Optional mido pygame backend: pip install pygame-ce
.\.venv\Scripts\python.exe -m cueplayer.app
```

If `.venv` is missing, create it first:

```powershell
py -3.14 -m venv .venv
```

## Setup (fresh)

```powershell
cd C:\Users\User\Projects\CuePlayer_didido
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
# MIDI: winmm works out of the box on Windows. Optional: pip install pygame-ce
.\.venv\Scripts\python.exe -m cueplayer.app
```

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Priority pain points (vs CuePoints)

1. Multi-channel audio routing on Windows (not 2CH-only)
2. Full Chinese / Unicode path and filename support
3. Multiple VJ clips / loops with audio-master sync
4. Better multi-version media replace / relink for rehearsals
5. Optional native NDI later; cue accuracy and MA export come first

## MA export next step

At the company machine, export golden XML from grandMA2 3.9.61.5 and grandMA3 2.3.2.
Follow `docs/spikes/MA_GOLDEN_XML.md`, then place files under `fixtures/ma2/` and `fixtures/ma3/`.
