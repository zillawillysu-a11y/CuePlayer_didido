# Next task

**Build and smoke-test CuePlayer 1.15 Windows artifacts.**

From the repository root, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build_windows.ps1 -Python .\.venv\Scripts\python.exe
```

Expected outputs (date suffix uses build day):

- `dist\CuePlayer-1.15-YYYYMMDD-win64.zip`
- `dist\CuePlayer-Setup-1.15.exe` when Inno Setup 6/7 is installed
- `dist\CuePlayer\CuePlayer.exe`

Launch the packaged EXE and confirm About/Splash/file properties show 1.15. Repeat a
short Art-Net receiver check, including TRANS + ArtTC and MTC + ArtTC, before sharing.
Do not start another feature or alter the stable MTC/audio architecture during release
packaging.
