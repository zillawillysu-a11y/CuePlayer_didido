"""Employee install / Windows packaging for CuePlayer.

Employees should **not** use Git. You (or a build PC) create a zip or Setup.exe
on **Windows**, then share that file (Google Drive / NAS / USB).

## What employees get

| Artifact | How they use it |
|----------|-----------------|
| `CuePlayer-1.0.5-YYYYMMDD-win64.zip` | Unzip → double-click `CuePlayer\CuePlayer.exe` |
| `CuePlayer-Setup-1.0.5.exe` | Run installer → Start Menu / Desktop shortcut |

Requirements on employee PCs: **Windows 10/11 64-bit**. No Python, no Git.

## Build (your Windows machine)

1. Checkout the tip branch you want to ship (or merge to a release tag).
2. Open PowerShell in the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

3. Share from `dist\`:
   - **Fast internal test:** the `.zip`
   - **Proper install (optional):** on **your** PC install [Inno Setup 7](https://jrsoftware.org/isdl.php) (e.g. 7.0.2 x64), re-run the script, send `CuePlayer-Setup-*.exe`. Employees do **not** install Inno Setup.

Optional flags:

```powershell
# Zip only (skip looking for Inno Setup)
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -SkipInno

# Folder only (no zip)
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -SkipZip -SkipInno
```

## Icon

Bundled (Dalmatian logo):

- `src/cueplayer/ui/assets/app_icon.ico` — Windows exe / taskbar / window
- `src/cueplayer/ui/assets/app_icon.png` — 512×512 PNG (transparent)
- `packaging/cueplayer.ico` — Inno Setup installer icon

PyInstaller and `app.py` pick these up automatically on the next Windows build.


## Employee handout

Send staff `docs/EMPLOYEE_INSTALL.md` (Chinese) together with the zip/Setup.
It tells them CuePlayer comes from **your** Drive/NAS (not GitHub), and NDI from:

- https://ndi.video/tools/  (NDI Tools, recommended)
- https://ndi.link/NDIRedistV6  (Runtime only)

## Notes

- Build **must** be on Windows (WASAPI, winmm MIDI, PyAV wheels).
- First build is large (often 200–500 MB) because of Qt + FFmpeg + NumPy/librosa + NDI.
- **NDI OUTPUT** is bundled (`cyndilib`). Each employee PC still needs
  **NDI Tools / Runtime** from [ndi.video](https://ndi.video) (same as your
  development machine). Without that runtime, NDI toggles will fail to open.
- After each feature merge, rebuild and send a new zip/Setup with a new date or version.
- Smoke-test the built `CuePlayer.exe` on a clean PC (or a second user account) before
  sending to the whole team: open project, play audio, show Video track, toggle NDI
  OUTPUT, export MA once.
