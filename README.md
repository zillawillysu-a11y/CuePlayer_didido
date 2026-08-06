# CuePlayer

Windows desktop timeline tool for lighting programmers.

Align multiple audio versions, LTC, VJ clips, and cue marks on one master timeline, then export Sequence / Timecode XML for grandMA2 and grandMA3.

## Status

**1.0.7** — Sprint 8 Video / Video Audio / waveform / Zoom / Mark-jump soak tip (CPU PyAV decode).

Ship tip / integrate to `master`: `cursor/release-1-0-7-028d`

Product requirements: `docs/PRODUCT_SPEC.md`  
User tips (shortcuts / Bundle / Relink): `docs/USER_MANUAL.md`  
Agent handoff: `AGENTS.md`

## Requirements

- Windows 11
- For **developers**: Python 3.13+, Git
- For **employees / testers**: no Git — use the Windows zip or Setup.exe (see `docs/DISTRIBUTION.md`)

## Employee install (no Git)

On a Windows build PC:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

Then send `dist\CuePlayer-*-win64.zip` (unzip → run `CuePlayer.exe`) or
`dist\CuePlayer-Setup-*.exe` if Inno Setup is installed.

## Update + run (this laptop)

```powershell
cd C:\Users\User\Projects\CuePlayer_didido
git fetch origin
git checkout cursor/release-1-0-7-028d
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

## Next after 1.0.7

1. Multi-audio version comparison + Align Anchors
2. Production soak / Depence GPU contention notes (CPU decode path)
3. MA Export Preview / Cue ID English–pinyin naming UI
4. Optional NDI polish only after cue accuracy stays solid

NDI OUTPUT is already shipped (needs NDI Tools/Runtime on each PC).
