"""Detect common grandMA2 / grandMA3 library folders on Windows."""

from __future__ import annotations

import re
from pathlib import Path

_PROGRAM_DATA = Path(r"C:\ProgramData")
_MA2_ROOT = _PROGRAM_DATA / "MA Lighting Technologies" / "grandma"
_MA3_ROOT = _PROGRAM_DATA / "MALightingTechnology"


def _version_key(name: str) -> tuple[int, ...]:
    """Sort gma2_V_3.9.63 / gma3_2.3.2 style folder names."""
    nums = re.findall(r"\d+", name)
    return tuple(int(n) for n in nums) if nums else (0,)


def default_ma2_export_dir() -> Path | None:
    """Newest installed grandMA2 `importexport` folder, if present."""
    if not _MA2_ROOT.is_dir():
        return None
    candidates: list[Path] = []
    for child in _MA2_ROOT.iterdir():
        if not child.is_dir() or not child.name.lower().startswith("gma2"):
            continue
        target = child / "importexport"
        if target.is_dir():
            candidates.append(target)
    if not candidates:
        return None
    candidates.sort(key=lambda p: _version_key(p.parent.name))
    return candidates[-1]


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
