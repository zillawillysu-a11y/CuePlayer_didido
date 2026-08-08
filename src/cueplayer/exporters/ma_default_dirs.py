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
    # Every full, untruncated installed version this computer actually has
    # (Windows uninstall registry + Start Menu/Desktop shortcut targets +
    # the coarser ProgramData library-folder scan as a last-resort
    # fallback) — see discover_installed_ma2_versions(). Defaults to ()
    # so existing 2-positional-arg construction keeps working unchanged.
    installed_versions: tuple[str, ...] = ()

    @property
    def recommended_version(self) -> str | None:
        if self.running_version and ma2_version_supported(self.running_version):
            return self.running_version
        precise = [v for v in self.installed_versions if ma2_version_supported(v)]
        if precise:
            return sorted(precise, key=_version_key)[-1]
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


def _looks_like_grandma2_identity(*fields: str) -> bool:
    """Identity check for a discovery candidate: at least one of its
    metadata fields (registry Publisher, the resolved executable's
    CompanyName/ProductName/FileDescription, or its install/target path)
    must plausibly name MA Lighting / grandMA2 onPC.

    A file having a well-formed x.x.x.x FileVersion is NOT sufficient on
    its own — msiexec.exe (Windows' own installer engine, which many
    "Uninstall <product>" shortcuts point their TargetPath at) has a
    perfectly valid FileVersion that simply tracks the Windows OS build
    (10.0.26100.xxxx-style), which is exactly the shape of the false
    positive this identity check exists to reject.
    """
    haystack = " ".join(field for field in fields if field).lower()
    if "ma lighting" in haystack:
        return True
    if re.search(r"grand\s*ma\s*2", haystack):
        return True
    return False


def _is_ma2_version_number(version: str) -> bool:
    """Every grandMA2 onPC release has been a 3.x build. Defense-in-depth
    only — never the sole reason a candidate is accepted or rejected; see
    _looks_like_grandma2_identity, which is the real identity gate."""
    key = _version_key(version)
    return bool(key) and key[0] == 3


def _run_powershell(command: str, *, timeout: float) -> str:
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout or ""


def _registry_ma2_versions_windows() -> tuple[str, ...]:
    """Full installed versions from the Windows uninstall registry.

    Scans both the native and WOW6432Node uninstall keys under HKLM, and
    HKCU (a per-user install), for any DisplayName matching grandMA2 onPC.
    DisplayVersion there can itself be an installer-authored 3-segment
    string, so when InstallLocation is present this cross-checks the real
    onPC executable's FileVersion (and reads its CompanyName/ProductName/
    FileDescription for identity validation) in the same PowerShell call,
    falling back to the registry's own DisplayVersion/Publisher when no
    matching executable is found.
    """
    command = (
        "$paths = @("
        "'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
        "'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
        "'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*'"
        "); "
        "Get-ItemProperty -Path $paths -ErrorAction SilentlyContinue | "
        "Where-Object { $_.DisplayName -match 'grandMA2.*onPC' } | "
        "ForEach-Object { "
        "$loc = $_.InstallLocation; "
        "$exeVer=''; $exeCompany=''; $exeProduct=''; $exeDesc=''; "
        "if ($loc -and (Test-Path -LiteralPath $loc)) { "
        "$exe = Get-ChildItem -LiteralPath $loc -Filter 'grandma2*.exe' -ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if (-not $exe) { $exe = Get-ChildItem -LiteralPath $loc -Filter 'gma2*.exe' -ErrorAction SilentlyContinue | Select-Object -First 1 }; "
        "if ($exe) { "
        "$vi = $exe.VersionInfo; "
        "$exeVer=$vi.FileVersion; $exeCompany=$vi.CompanyName; $exeProduct=$vi.ProductName; $exeDesc=$vi.FileDescription "
        "} "
        "}; "
        "\"$($_.DisplayVersion)|$loc|$($_.Publisher)|$exeVer|$exeCompany|$exeProduct|$exeDesc\" "
        "}"
    )
    versions: list[str] = []
    for line in _run_powershell(command, timeout=5).splitlines():
        parts = line.split("|", 6)
        if len(parts) < 7:
            continue
        display_version, install_location, publisher, exe_version, exe_company, exe_product, exe_desc = (
            part.strip() for part in parts
        )
        version = exe_version or display_version
        if not version or not _is_ma2_version_number(version):
            continue
        if not _looks_like_grandma2_identity(
            publisher, exe_company, exe_product, exe_desc, install_location
        ):
            continue
        versions.append(version)
    return tuple(versions)


def _shortcut_ma2_versions_windows() -> tuple[str, ...]:
    """Full installed versions resolved from Start Menu / Desktop .lnk
    shortcuts whose name matches grandMA2 onPC (excluding "Uninstall ..."
    shortcuts, which point at a generic uninstall helper — often
    msiexec.exe — rather than the real onPC executable): each shortcut's
    target executable is resolved via the WScript.Shell COM object, then
    its FileVersion and CompanyName/ProductName/FileDescription are read
    for identity validation the same way as the registry scan."""
    command = (
        "$shell = New-Object -ComObject WScript.Shell; "
        "$dirs = @("
        "\"$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\","
        "\"$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\","
        "\"$env:PUBLIC\\Desktop\","
        "\"$env:USERPROFILE\\Desktop\""
        "); "
        "Get-ChildItem -Path $dirs -Filter *.lnk -Recurse -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Name -match 'grandMA2.*onPC' -and $_.Name -notmatch 'uninstall' } | "
        "ForEach-Object { "
        "$t = $shell.CreateShortcut($_.FullName).TargetPath; "
        "if ($t -and (Test-Path -LiteralPath $t)) { "
        "$vi = (Get-Item -LiteralPath $t).VersionInfo; "
        "\"$($vi.FileVersion)|$($vi.CompanyName)|$($vi.ProductName)|$($vi.FileDescription)|$t\" "
        "} }"
    )
    versions: list[str] = []
    for line in _run_powershell(command, timeout=8).splitlines():
        parts = line.split("|", 4)
        if len(parts) < 5:
            continue
        version, company, product, description, target_path = (part.strip() for part in parts)
        if not version or not _is_ma2_version_number(version):
            continue
        if not _looks_like_grandma2_identity(company, product, description, target_path):
            continue
        versions.append(version)
    return tuple(versions)


def merge_installed_ma2_versions(
    installations: tuple[Ma2Installation, ...],
    registry_versions: tuple[str, ...],
    shortcut_versions: tuple[str, ...],
) -> tuple[str, ...]:
    """Combine every discovery source into one deduplicated, numerically
    sorted, full-precision version list.

    Registry/shortcut versions are usually the real 4-segment FileVersion
    (e.g. 3.9.60.91). The ProgramData library-folder scan only ever
    recovers 3 segments (its "gma2_V_3.9.60" folder name is genuinely all
    MA2 itself records there, and several onPC point-releases can share one
    such folder) — so a folder-derived version is only used as a fallback
    for an X.Y.Z family where NEITHER other source found anything, never
    mixed in alongside a precise version for the same family. Multiple
    distinct 4-segment versions sharing one X.Y.Z (3.9.60.18/.74/.89/.91)
    are all kept.
    """
    precise_by_prefix: dict[tuple[int, ...], set[str]] = {}
    for version in (*registry_versions, *shortcut_versions):
        version = version.strip()
        if not version:
            continue
        precise_by_prefix.setdefault(_version_key(version)[:3], set()).add(version)

    result: set[str] = set()
    for versions in precise_by_prefix.values():
        result.update(versions)
    for item in installations:
        prefix = _version_key(item.version)[:3]
        if prefix not in precise_by_prefix:
            result.add(item.version)
    return tuple(sorted(result, key=_version_key))


def discover_ma2_environment(
    root: Path = _MA2_ROOT,
    running_version_reader: Callable[[], str | None] = _running_ma2_version_windows,
    registry_versions_reader: Callable[[], tuple[str, ...]] = _registry_ma2_versions_windows,
    shortcut_versions_reader: Callable[[], tuple[str, ...]] = _shortcut_ma2_versions_windows,
) -> Ma2Discovery:
    installations = discover_ma2_installations(root)
    installed_versions = merge_installed_ma2_versions(
        installations, registry_versions_reader(), shortcut_versions_reader()
    )
    return Ma2Discovery(installations, running_version_reader(), installed_versions)


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
