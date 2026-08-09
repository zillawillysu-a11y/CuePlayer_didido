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


def _is_ma2_version_number(version: str) -> bool:
    """Every grandMA2 onPC release has been a 3.x build. Defense-in-depth
    only — never the sole reason a candidate is accepted; see the
    identity checks in each reader below."""
    key = _version_key(version)
    return bool(key) and key[0] == 3


def _is_ma2_executable_filename(path: str) -> bool:
    """Identity check for a shortcut TARGET: does it actually point at
    grandMA2 onPC's own executable (gma2onpc*.exe / grandma2*.exe), not
    some other program a shortcut with a matching *name* happens to
    launch?

    Confirmed on a real machine: MA Lighting's installer also creates an
    "Open Show Folder grandMA2 onPC X.X.X.X" shortcut whose TargetPath is
    literally C:\\Windows\\explorer.exe — its *name* matches
    "grandMA2.*onPC" same as the real launch shortcuts, but its target is
    Microsoft's own file explorer, whose FileVersion just tracks the
    Windows OS build (10.0.26100.8875-style — the exact false positive
    this exists to reject). gma2onpc.exe itself embeds no VersionInfo at
    all (FileVersion/CompanyName/ProductName all empty), so identity has
    to come from the target path's own filename, not its metadata.
    """
    if not path:
        return False
    name = Path(path).name.lower()
    return bool(re.match(r"(gma2onpc|grandma2)[^\\/]*\.exe$", name))


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
    HKCU (a per-user install), for any DisplayName matching grandMA2 onPC
    — MA Lighting's installer names each entry literally
    "grandMA2 onPC X.Y.Z.W", and confirmed on a real machine,
    DisplayVersion/Publisher/InstallLocation can all be blank there, so
    the version is parsed straight out of that DisplayName text (which is
    also the identity signal: Windows' own curated per-product field
    already matched grandMA2 onPC, same gate the pre-identity-validation
    code effectively relied on). If InstallLocation *is* present and its
    real onPC executable's own FileVersion is non-empty, that is used
    instead since it can only be more precise, never less.
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
        "$exeVer=''; "
        "if ($loc -and (Test-Path -LiteralPath $loc)) { "
        "$exe = Get-ChildItem -LiteralPath $loc -Filter 'gma2onpc*.exe' -ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if (-not $exe) { $exe = Get-ChildItem -LiteralPath $loc -Filter 'grandma2*.exe' -ErrorAction SilentlyContinue | Select-Object -First 1 }; "
        "if ($exe) { $exeVer = $exe.VersionInfo.FileVersion } "
        "}; "
        "\"$($_.DisplayName)|$exeVer\" "
        "}"
    )
    versions: list[str] = []
    for line in _run_powershell(command, timeout=5).splitlines():
        display_name, _, exe_version = line.partition("|")
        display_name = display_name.strip()
        exe_version = exe_version.strip()
        name_match = re.search(r"\d+(?:\.\d+){2,3}", display_name)
        version = exe_version or (name_match.group(0) if name_match else "")
        if not version or not _is_ma2_version_number(version):
            continue
        versions.append(version)
    return tuple(versions)


def _shortcut_ma2_versions_windows() -> tuple[str, ...]:
    """Full installed versions resolved from Start Menu / Desktop .lnk
    shortcuts whose name matches grandMA2 onPC (excluding "Uninstall ..."
    shortcuts): the version is parsed from the shortcut's own filename
    (MA Lighting names them "grandMA2 onPC X.Y.Z.W[.lnk| CleanStart.lnk]"
    — confirmed reliable on a real machine, unlike gma2onpc.exe's own
    VersionInfo, which is entirely empty), and identity is validated by
    requiring the shortcut's resolved TARGET executable to itself be
    named like the real onPC binary — see _is_ma2_executable_filename for
    why that, not FileVersion/CompanyName, is the actual identity gate
    here."""
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
        "\"$($_.Name)|$t\" "
        "}"
    )
    versions: list[str] = []
    for line in _run_powershell(command, timeout=8).splitlines():
        name, _, target = line.partition("|")
        name = name.strip()
        target = target.strip()
        match = re.search(r"\d+(?:\.\d+){2,3}", name)
        if match is None:
            continue
        version = match.group(0)
        if not _is_ma2_version_number(version):
            continue
        if not _is_ma2_executable_filename(target):
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


def discover_ma2_environment_fast(root: Path = _MA2_ROOT) -> Ma2Discovery:
    """Filesystem-only discovery used while loading a project/UI."""
    installations = discover_ma2_installations(root)
    return Ma2Discovery(
        installations=installations,
        running_version=None,
        installed_versions=tuple(item.version for item in installations),
    )


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


def export_path_matches_console(path: str | Path, console: str) -> bool:
    """Public guard used before saving/exporting a console-specific path."""
    return _path_matches_console(Path(path), console)
