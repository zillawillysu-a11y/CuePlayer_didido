# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for CuePlayer Windows builds (onedir).

Build on Windows only (WASAPI / winmm / PyAV wheels):

    powershell -ExecutionPolicy Bypass -File packaging\\build_windows.ps1
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
ASSETS = SRC / "cueplayer" / "ui" / "assets"

datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = [
    "cueplayer",
    "cueplayer.app",
    "cueplayer.__main__",
    "pypinyin",
    "mido",
    "mido.backends.rtmidi",
    "numpy",
    "soundfile",
    "sounddevice",
    "av",
    "librosa",
    "cyndilib",
    "cyndilib.sender",
    "cyndilib.video_frame",
    "cyndilib.wrapper.ndi_structs",
]

# Bundle UI assets (checkmark, optional app icon).
if ASSETS.is_dir():
    datas += collect_data_files("cueplayer", includes=["ui/assets/*"])

for pkg in ("PySide6", "av", "soundfile", "certifi", "cyndilib"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception as exc:  # noqa: BLE001
        print(f"warning: collect_all({pkg!r}) failed: {exc}", file=sys.stderr)

# librosa pulls scipy / numba / sklearn pieces — collect what is installed.
for pkg in ("librosa", "scipy", "sklearn", "numba", "llvmlite", "resampy", "pooch", "lazy_loader"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        pass

icon_file = None
for candidate in (
    ASSETS / "app_icon.ico",
    ASSETS / "cueplayer.ico",
    ROOT / "packaging" / "cueplayer.ico",
):
    if candidate.is_file():
        icon_file = str(candidate)
        break

a = Analysis(
    [str(SRC / "cueplayer" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Dev / test only.
        "pytest",
        "IPython",
        "jupyter",
        "tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CuePlayer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app — no black console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CuePlayer",
)
