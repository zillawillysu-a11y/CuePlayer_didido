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
    "cueplayer.media.video_waveform_worker",
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

# Bundle UI assets (checkmark, optional app icon) + Web Remote static UI.
if ASSETS.is_dir():
    datas += collect_data_files("cueplayer", includes=["ui/assets/*"])
datas += collect_data_files("cueplayer", includes=["web_remote/static/*"])
hiddenimports += [
    "cueplayer.web_remote",
    "cueplayer.web_remote.server",
    "cueplayer.web_remote.bridge",
    "cueplayer.web_remote.webrtc_listen",
    "aiortc",
    "aioice",
    "av.audio.resampler",
]

# --- Qt packaging slimming (Cleanup Phase 1) -------------------------------
# `collect_all("PySide6")` grabs the *entire* Qt6 SDK unconditionally.
# src/ only ever imports PySide6.QtCore / QtGui / QtWidgets (confirmed by a
# full grep audit — see PROJECT_SLIM_REPORT.md).
#
# IMPORTANT, learned by actually building and measuring (not just grepping):
# PySide6's own PyInstaller hooks do a binary *dependency walk* on top of
# whatever collect_all() returns, independent of this filter and of
# Analysis(excludes=...). For QtQuick/QtQml specifically, that walk
# re-adds the entire Quick/Qml/Qt3D DLL cluster (~60 files) even with every
# exclusion mechanism below applied — hard evidence that Qt6's own native
# Windows 11 "FluentWinUI3" style (the default QtWidgets style on Windows
# 11) has a real runtime dependency on QtQuick, not just an unused sibling
# module. Do NOT try to force those DLLs out — the earlier PROJECT_SLIM_
# REPORT.md classification of QtQuick/QML as "LIKELY SAFE" was based on
# static grep only and is corrected here based on this build-level finding.
# Same walk fully restores the `plugins/tls`, `plugins/geoservices`, and
# `plugins/networkinformation` folders (measured: byte-identical to the
# unfiltered build), so those three are intentionally left out of the
# marker list below rather than kept as dead-weight exclusions that do
# nothing. Everything still listed here was verified, by an actual build,
# to be removed and to leave a working app (see PROJECT_SLIM_REPORT.md
# Phase 1 results for the before/after measurement and smoke test).
_QT_EXCLUDE_MARKERS = (
    "webengine",  # Qt6WebEngineCore.dll, Qt6WebEngineWidgets.dll, QtWebEngineWidgets.pyd, qtwebengine_devtools_resources*.pak, qtwebengine_locales/, PySide6/typesystems/typesystem_webengine*.xml, metatypes/qt6webengine*_metatypes.json, …
    "/qml/",       # QML script/resource tree (verified removed — the QtQuick/QtQml *DLLs* stay, see note above)
    "/translations/",  # verified: 60 MB -> 8.4 MB; PySide6's hook still restores a base qt_*/qt_help_* catalog Qt itself may reach for in standard dialogs — that residual is left alone rather than force-stripped further
    "/plugins/sqldrivers/",
    "/plugins/sceneparsers/",
    "/plugins/assetimporters/",
    "/plugins/renderers/",
    "/plugins/canbus/",
    "/plugins/multimedia/",   # Qt Multimedia's own bundled backend plugin, not PyAV — CuePlayer's real, used FFmpeg (av.libs) is untouched
    "/plugins/designer/",
    "/plugins/position/",
    "/plugins/sensors/",
    "/plugins/texttospeech/",
    "/plugins/webview/",
    "/plugins/qmltooling/",
)


def _qt_path_excluded(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return any(marker in normalized for marker in _QT_EXCLUDE_MARKERS)


def _filter_qt_entries(entries):
    """Drop (src, dest) tuples whose src OR dest path matches an excluded
    Qt component. Checking both sides is deliberate: PyInstaller's own
    dest convention for root-level DLLs collapses everything under
    'PySide6/', so the real signal for e.g. Qt6WebEngineCore.dll is only
    visible in the absolute *source* path."""
    kept = []
    dropped_size = 0
    for entry in entries:
        src, dest = entry[0], entry[1]
        if _qt_path_excluded(src) or _qt_path_excluded(dest):
            try:
                dropped_size += Path(src).stat().st_size
            except OSError:
                pass
            continue
        kept.append(entry)
    return kept, len(entries) - len(kept), dropped_size


# Blocks the *Python* import surface (the .pyd binding module) for
# submodules src/ never imports. This does not guarantee the underlying
# native Qt DLL also disappears — see the QtQuick/QtQml note above, where
# PySide6's own hook restores the DLL regardless via a binary dependency
# walk that this hiddenimport filter has no influence over.
_QT_HIDDENIMPORT_EXCLUDE_PREFIXES = (
    "PySide6.QtWebEngine",
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.QtDesigner",
    "PySide6.QtSql",
    "PySide6.QtMultimedia",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebView",
    "PySide6.QtSerialBus",
    "PySide6.Qt3D",
)

for pkg in ("PySide6", "av", "soundfile", "certifi", "cyndilib", "aiortc", "aioice"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        if pkg == "PySide6":
            pkg_datas, n_datas_dropped, datas_bytes = _filter_qt_entries(pkg_datas)
            pkg_binaries, n_bin_dropped, bin_bytes = _filter_qt_entries(pkg_binaries)
            pkg_hidden = [
                h
                for h in pkg_hidden
                if not any(h.startswith(p) for p in _QT_HIDDENIMPORT_EXCLUDE_PREFIXES)
            ]
            print(
                f"Qt slim: dropped {n_datas_dropped} data + {n_bin_dropped} binary "
                f"entries (~{(datas_bytes + bin_bytes) / 1_048_576:.1f} MB) from "
                f"collect_all('PySide6') — see PROJECT_SLIM_REPORT.md",
                file=sys.stderr,
            )
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception as exc:  # noqa: BLE001
        print(f"warning: collect_all({pkg!r}) failed: {exc}", file=sys.stderr)

# librosa pulls scipy / numba / sklearn pieces — collect what is installed.
# Fail the build if core scientific packs are missing (silent pass shipped
# broken BPM detect that flash-quit at ~30% on employee PCs).
_REQUIRED_BPM_PACKS = ("numpy", "scipy", "soundfile")
_OPTIONAL_BPM_PACKS = (
    "librosa",
    "sklearn",
    "numba",
    "llvmlite",
    "soxr",
    "resampy",
    "pooch",
    "lazy_loader",
    "msgpack",
    "audioread",
    "joblib",
    "decorator",
)
for pkg in _REQUIRED_BPM_PACKS:
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden
for pkg in _OPTIONAL_BPM_PACKS:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception as exc:  # noqa: BLE001
        print(f"warning: collect_all({pkg!r}) failed: {exc}", file=sys.stderr)

# Runtime hook: disable Numba JIT before any worker imports librosa.
_HOOKS = ROOT / "packaging" / "hooks"
if _HOOKS.is_dir():
    hookspath = [str(_HOOKS)]
else:
    hookspath = []

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
    hookspath=hookspath,
    hooksconfig={},
    runtime_hooks=[str(p) for p in sorted(_HOOKS.glob("pyi_rth_*.py"))] if _HOOKS.is_dir() else [],
    excludes=[
        # Dev / test only.
        "pytest",
        "IPython",
        "jupyter",
        "tkinter",
        # Qt packaging slimming (Cleanup Phase 1) — belt-and-suspenders on
        # top of the collect_all() filtering above, in case PyInstaller's
        # own modulegraph analysis (independent of our manual collect_all
        # call) would otherwise pull one of these in via a hook.
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtQuickControls2",
        "PySide6.QtQml",
        "PySide6.QtQmlModels",
        "PySide6.QtDesigner",
        "PySide6.QtSql",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtPositioning",
        "PySide6.QtSensors",
        "PySide6.QtTextToSpeech",
        "PySide6.QtWebView",
        "PySide6.QtSerialBus",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DExtras",
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
