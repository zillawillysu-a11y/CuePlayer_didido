"""Employee install / Windows packaging for CuePlayer.

Employees should **not** use Git. You (or a build PC) create a zip or Setup.exe
on **Windows**, then share that file (Google Drive / NAS / USB).

## What employees get

| Artifact | How they use it |
|----------|-----------------|
| `CuePlayer-0.1.0-YYYYMMDD-win64.zip` | Unzip → double-click `CuePlayer\CuePlayer.exe` |
| `CuePlayer-Setup-0.1.0.exe` | Run installer → Start Menu / Desktop shortcut |

Requirements on employee PCs: **Windows 10/11 64-bit**. No Python, no Git.

## Build (your Windows machine)

1. Checkout the tip branch you want to ship (or merge to a release tag).
2. Open PowerShell in the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

3. Share from `dist\`:
   - **Fast internal test:** the `.zip`
   - **Proper install:** install [Inno Setup 6](https://jrsoftware.org/isinfo.php), re-run the script, send `CuePlayer-Setup-*.exe`

Optional flags:

```powershell
# Zip only (skip looking for Inno Setup)
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -SkipInno

# Folder only (no zip)
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -SkipZip -SkipInno
```

## Icon (optional but recommended)

Put either file here before building:

- `src/cueplayer/ui/assets/app_icon.ico`  (best for Windows exe + taskbar)
- `src/cueplayer/ui/assets/app_icon.png`

The build script / PyInstaller will pick it up automatically. Without it, Windows
shows a generic executable icon.

## Notes

- Build **must** be on Windows (WASAPI, winmm MIDI, PyAV wheels).
- First build is large (often 200–500 MB) because of Qt + FFmpeg + NumPy/librosa.
- NDI (`cyndilib`) is **not** bundled by default; cue accuracy testing does not need it.
- After each feature merge, rebuild and send a new zip/Setup with a new date or version.
- Smoke-test the built `CuePlayer.exe` on a clean PC (or a second user account) before
  sending to the whole team: open project, play audio, show Video track, export MA once.
