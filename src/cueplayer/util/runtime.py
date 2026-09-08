"""Runtime helpers for source installs vs frozen (PyInstaller) builds."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Directory that contains CuePlayer.exe (frozen) or the package root."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def meipass_dir() -> Path | None:
    """PyInstaller unpack directory, or None when running from source."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return None


def package_root() -> Path:
    """Root of the ``cueplayer`` package (source or inside the frozen bundle)."""
    return Path(__file__).resolve().parents[1]


def ui_assets_dir() -> Path:
    return package_root() / "ui" / "assets"


def app_icon_path() -> Path | None:
    """Preferred window / installer icon if present."""
    assets = ui_assets_dir()
    for name in ("app_icon.ico", "app_icon.png", "cueplayer.ico", "cueplayer.png"):
        path = assets / name
        if path.is_file():
            return path
    return None
