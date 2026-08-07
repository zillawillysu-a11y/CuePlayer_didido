"""Detect common grandMA2 / grandMA3 library folders on Windows."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_PROGRAM_DATA = Path(r"C:\ProgramData")
_MA2_ROOT = _PROGRAM_DATA / "MA Lighting Technologies" / "grandma"
_MA3_ROOT = _PROGRAM_DATA / "MALightingTechnology"
MA2_MINIMUM_VERSION = "3.3.4.3"


@dataclass(frozen=True)
class Ma2Installation:
    version: str
    library_dir: Path
    importexport_dir: Path


@dataclass(frozen=True)
class Ma2Discovery:
    installations: tuple[Ma2Installation, ...]
    running_version: str | None

    @property
    def recommended_version(self) -> str | None:
        if self.running_version and ma2_version_supported(self.running_version):
            return self.running_version
        supported = [item for item in self.installations if ma2_version_supported(item.version)]
        return supported[-1].version if supported else None


def _version_key(name: str) -> tuple[int, ...]:
    """Sort gma2_V_3.9.63 / gma3_2.3.2 style folder names."""
    nums = re.findall(r"\d+", name)
    return tuple(int(n) for n in nums) if nums else (0,)


def ma2_version_supported(version: str) -> bool:
    return _version_key(version) >= _version_key(MA2_MINIMUM_VERSION)


def discover_ma2_installations(root: Path = _MA2_ROOT) -> tuple[Ma2Installation, ...]:
    """Enumerate installed MA2 libraries without modifying their contents."""
    if not root.is_dir():
        return ()
    found: list[Ma2Installation] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        match = re.fullmatch(r"gma2_V_(\d+(?:\.\d+){2,3})", child.name, re.IGNORECASE)
        if match is None:
            continue
        importexport = child / "importexport"
        if importexport.is_dir():
            found.append(Ma2Installation(match.group(1), child, importexport))
    return tuple(sorted(found, key=lambda item: _version_key(item.version)))


def _running_ma2_version_windows() -> str | None:
    """Read the active grandMA2 onPC executable FileVersion through PowerShell."""
    command = (
        "$p=Get-CimInstance Win32_Process | Where-Object { "
        "$_.Name -match '^(grandma2|gma2).*\\.exe$' -and $_.ExecutablePath }; "
        "$p | ForEach-Object { (Get-Item -LiteralPath $_.ExecutablePath).VersionInfo.FileVersion }"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    versions = re.findall(r"\d+(?:\.\d+){2,3}", result.stdout or "")
    return max(versions, key=_version_key) if versions else None


def discover_ma2_environment(
    root: Path = _MA2_ROOT,
    running_version_reader: Callable[[], str | None] = _running_ma2_version_windows,
) -> Ma2Discovery:
    return Ma2Discovery(discover_ma2_installations(root), running_version_reader())


def ma2_export_dir_for_version(
    version: str, installations: tuple[Ma2Installation, ...]
) -> Path | None:
    """Match a full build (3.9.63.6) to its library folder (gma2_V_3.9.63)."""
    wanted = _version_key(version)[:3]
    matches = [item for item in installations if _version_key(item.version)[:3] == wanted]
    return matches[-1].importexport_dir if matches else None


def ma2_version_from_path(path: Path | str) -> str | None:
    match = re.search(
        r"gma2_V_(\d+(?:\.\d+){2,3})",
        str(path).replace("/", "\\"),
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def default_ma2_export_dir() -> Path | None:
    """Newest installed grandMA2 `importexport` folder, if present."""
    installations = discover_ma2_installations()
    return installations[-1].importexport_dir if installations else None


def resolve_ma2_pool_dirs(root: Path) -> tuple[Path, Path, Path]:
    """
    Map an export root to MA2 library folders.

    Returns (importexport_dir, plugins_dir, macros_dir).

    grandMA2 Import UI:
    - Sequence / Timecode → ``importexport/``
    - Plugin pool → ``plugins/`` (``.xml`` + sibling ``.lua``)
    - Macro pool → ``macros/``

    Accepts ``…/gma2_V_*/importexport``, ``…/gma2_V_*``, or any folder
    (then plugin/macro stay beside sequences for tests / custom paths).
    """
    root = Path(root)
    name = root.name.lower()
    if name == "importexport":
        library = root.parent
        return root, library / "plugins", library / "macros"
    if name.startswith("gma2"):
        return root / "importexport", root / "plugins", root / "macros"
    # Custom / test folder: keep everything in one place.
    return root, root, root


def default_ma3_export_dir() -> Path | None:
    """
    Preferred MA3 root: `gma3_library`.

    Exporter then writes into datapools/sequences, timecodes, macros.
    """
    library = _MA3_ROOT / "gma3_library"
    if library.is_dir():
        return library
    if not _MA3_ROOT.is_dir():
        return None
    versions = [
        child
        for child in _MA3_ROOT.iterdir()
        if child.is_dir() and child.name.lower().startswith("gma3_")
    ]
    if not versions:
        return None
    versions.sort(key=lambda p: _version_key(p.name))
    return versions[-1]


def resolve_export_dir(console: str, remembered: str | None = None) -> str:
    """
    Pick an output folder string for the export dialog.

    Order: remembered path (if it still exists and matches the console) →
    detected MA default → empty.
    """
    if remembered:
        path = Path(remembered)
        if path.is_dir() and _path_matches_console(path, console):
            return str(path)
    detected = default_ma2_export_dir() if console == "ma2" else default_ma3_export_dir()
    return str(detected) if detected is not None else ""


def _path_matches_console(path: Path, console: str) -> bool:
    """Reject a remembered folder that clearly belongs to the other console."""
    text = str(path).replace("/", "\\").lower()
    if console == "ma2":
        if "malightingtechnology" in text or "gma3_library" in text:
            return False
        return True
    # ma3
    if "ma lighting technologies" in text or "\\grandma\\" in text:
        return False
    if path.name.lower() == "importexport":
        return False
    return True
