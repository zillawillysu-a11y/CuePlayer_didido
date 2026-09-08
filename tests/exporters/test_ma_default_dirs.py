"""Tests for MA default export directory detection."""

from __future__ import annotations

from pathlib import Path

from cueplayer.exporters import ma_default_dirs
from cueplayer.exporters.ma_default_dirs import (
    Ma2Installation,
    discover_ma2_environment,
    discover_ma2_installations,
    default_ma2_export_dir,
    default_ma3_export_dir,
    ma2_export_dir_for_version,
    ma2_version_from_path,
    ma2_version_supported,
    merge_installed_ma2_versions,
    resolve_export_dir,
)
from cueplayer.exporters.ma_default_dirs import (
    _is_ma2_executable_filename,
    _is_ma2_version_number,
    _registry_ma2_versions_windows,
    _shortcut_ma2_versions_windows,
)


def test_resolve_prefers_remembered(tmp_path: Path) -> None:
    remembered = tmp_path / "custom"
    remembered.mkdir()
    assert resolve_export_dir("ma2", str(remembered)) == str(remembered)


def test_resolve_falls_back_when_remembered_missing(tmp_path: Path) -> None:
    missing = tmp_path / "gone"
    result = resolve_export_dir("ma2", str(missing))
    detected = default_ma2_export_dir()
    if detected is not None:
        assert result == str(detected)
    else:
        assert result == ""


def test_detect_ma_folders_if_installed() -> None:
    ma2 = default_ma2_export_dir()
    ma3 = default_ma3_export_dir()
    if ma2 is not None:
        assert ma2.name == "importexport"
        assert ma2.is_dir()
    if ma3 is not None:
        assert ma3.is_dir()


def test_discover_ma2_installations_sorts_and_ignores_noise(tmp_path: Path) -> None:
    for name in ("gma2_V_3.9.60", "gma2_V_3.3.4", "gma2_V_3.9.63"):
        (tmp_path / name / "importexport").mkdir(parents=True)
    (tmp_path / "gma2_V_invalid" / "importexport").mkdir(parents=True)
    (tmp_path / "gma2_V_3.9.61").mkdir()

    found = discover_ma2_installations(tmp_path)

    assert [item.version for item in found] == ["3.3.4", "3.9.60", "3.9.63"]
    assert found[-1].importexport_dir.name == "importexport"


def test_discovery_prefers_supported_running_full_build(tmp_path: Path) -> None:
    (tmp_path / "gma2_V_3.9.60" / "importexport").mkdir(parents=True)
    # Registry/shortcut readers stubbed to () — this is a determinism test,
    # not a test of the real host machine's actual MA2 installs.
    discovery = discover_ma2_environment(tmp_path, lambda: "3.9.63.6", lambda: (), lambda: ())
    assert discovery.running_version == "3.9.63.6"
    assert discovery.recommended_version == "3.9.63.6"


def test_discovery_falls_back_to_newest_supported_install(tmp_path: Path) -> None:
    for name in ("gma2_V_3.2.2", "gma2_V_3.3.4", "gma2_V_3.9.60"):
        (tmp_path / name / "importexport").mkdir(parents=True)
    discovery = discover_ma2_environment(tmp_path, lambda: None, lambda: (), lambda: ())
    assert discovery.recommended_version == "3.9.60"
    assert not ma2_version_supported("3.3.4.2")
    assert ma2_version_supported("3.3.4.3")


def test_merge_keeps_every_distinct_patch_sharing_one_family(tmp_path: Path) -> None:
    """Willy's real machine has 3.9.60.18 / .74 / .89 / .91 installed at
    once — all four must survive, none collapsed into a generic "3.9.60"."""
    registry_versions = ("3.9.60.18", "3.9.60.74", "3.9.60.89", "3.9.60.91")
    merged = merge_installed_ma2_versions((), registry_versions, ())
    assert merged == ("3.9.60.18", "3.9.60.74", "3.9.60.89", "3.9.60.91")


def test_merge_prefers_precise_version_over_folder_derived_generic() -> None:
    """A ProgramData library folder only ever yields a 3-segment name
    ("3.9.63") — when the registry/shortcut scan found the real 4-segment
    build for that same X.Y.Z family, the generic 3-segment one must not
    also appear (that mixing is exactly what looked like a bug)."""
    installations = (Ma2Installation("3.9.63", Path("lib"), Path("ie")),)
    merged = merge_installed_ma2_versions(installations, ("3.9.63.6",), ())
    assert merged == ("3.9.63.6",)


def test_merge_falls_back_to_folder_derived_when_nothing_precise_found() -> None:
    """A family with no registry/shortcut match at all still shows up,
    using whatever the folder scan found, rather than being dropped."""
    installations = (Ma2Installation("3.7.0", Path("lib"), Path("ie")),)
    merged = merge_installed_ma2_versions(installations, (), ())
    assert merged == ("3.7.0",)


def test_merge_deduplicates_identical_versions_from_multiple_sources() -> None:
    merged = merge_installed_ma2_versions((), ("3.9.63.6",), ("3.9.63.6",))
    assert merged == ("3.9.63.6",)


def test_merge_sorts_numerically_not_lexically() -> None:
    """Lexical order would put "3.9.60.91" before "3.9.9.1" (since '6' <
    '9'), which is numerically backwards."""
    merged = merge_installed_ma2_versions((), ("3.9.60.91", "3.9.9.1"), ())
    assert merged == ("3.9.9.1", "3.9.60.91")


def test_discover_ma2_environment_combines_registry_and_shortcut_sources(
    tmp_path: Path,
) -> None:
    (tmp_path / "gma2_V_3.7.0" / "importexport").mkdir(parents=True)
    discovery = discover_ma2_environment(
        tmp_path,
        lambda: None,
        lambda: ("3.9.60.91", "3.9.61.5"),
        lambda: ("3.9.63.6",),
    )
    assert discovery.installed_versions == ("3.7.0", "3.9.60.91", "3.9.61.5", "3.9.63.6")
    assert discovery.recommended_version == "3.9.63.6"


_WILLY_REAL_VERSIONS = (
    "3.1.2.5", "3.3.4.3", "3.7.0.1", "3.7.0.5", "3.8.0.0", "3.9.0.3",
    "3.9.60.18", "3.9.60.74", "3.9.60.89", "3.9.60.91", "3.9.61.5", "3.9.63.6",
)


def test_end_to_end_matches_real_machine_registry_and_shortcut_output(monkeypatch) -> None:
    """End-to-end regression test built directly from Willy's real
    diagnostic PowerShell output: registry DisplayVersion/Publisher/
    InstallLocation all blank (only DisplayName usable), and every real
    install also has an "Open Show Folder grandMA2 onPC X.X.X.X" shortcut
    targeting C:\\Windows\\explorer.exe alongside its two real launch
    shortcuts. The merged result must be exactly the 12 real versions,
    full precision, no explorer.exe-sourced 10.0.26100.8875."""
    registry_output = "".join(f"grandMA2 onPC {v}|\n" for v in _WILLY_REAL_VERSIONS)

    shortcut_lines = []
    for v in _WILLY_REAL_VERSIONS:
        real_exe = f"C:\\Program Files\\MA Lighting Technologies\\grandma\\grandMA2 onPC {v}\\gma2onpc.exe"
        shortcut_lines.append(f"grandMA2 onPC {v}.lnk|{real_exe}")
        shortcut_lines.append(f"grandMA2 onPC {v} CleanStart.lnk|{real_exe}")
        shortcut_lines.append(f"Open Show Folder grandMA2 onPC {v}.lnk|C:\\Windows\\explorer.exe")
    shortcut_output = "".join(line + "\n" for line in shortcut_lines)

    def fake_run_powershell(command: str, *, timeout: float) -> str:
        # Distinguish which script ran the same way discover_ma2_environment
        # calls each reader — by which command text is being executed.
        if "WScript.Shell" in command:
            return shortcut_output
        return registry_output

    monkeypatch.setattr(ma_default_dirs, "_run_powershell", fake_run_powershell)

    discovery = discover_ma2_environment(
        Path("/nonexistent"), lambda: None,
        ma_default_dirs._registry_ma2_versions_windows,
        ma_default_dirs._shortcut_ma2_versions_windows,
    )
    assert discovery.installed_versions == _WILLY_REAL_VERSIONS
    assert "10.0.26100.8875" not in discovery.installed_versions
    assert discovery.recommended_version == "3.9.63.6"


def test_is_ma2_version_number_requires_major_version_3() -> None:
    assert _is_ma2_version_number("3.9.60.91")
    assert _is_ma2_version_number("3.3.4.3")
    # 10.0.26100.8875 is Windows' own OS build numbering (explorer.exe's
    # FileVersion), not a grandMA2 onPC version.
    assert not _is_ma2_version_number("10.0.26100.8875")
    assert not _is_ma2_version_number("")


def test_is_ma2_executable_filename_matches_the_real_onpc_binary() -> None:
    assert _is_ma2_executable_filename(r"C:\Program Files\MA Lighting Technologies\grandma\grandMA2 onPC 3.9.60.91\gma2onpc.exe")
    assert _is_ma2_executable_filename(r"C:\somewhere\grandMA2onPC_x64.exe")
    # Confirmed on a real machine: MA Lighting also ships an "Open Show
    # Folder grandMA2 onPC X.X.X" shortcut whose name matches the
    # grandMA2/onPC filter same as the real launch shortcuts, but whose
    # target is Microsoft's own file explorer — this must be rejected.
    assert not _is_ma2_executable_filename(r"C:\Windows\explorer.exe")
    assert not _is_ma2_executable_filename(r"C:\Windows\System32\msiexec.exe")
    assert not _is_ma2_executable_filename("")


def test_registry_scan_parses_version_from_display_name(monkeypatch) -> None:
    """Confirmed on a real machine: DisplayVersion/Publisher/InstallLocation
    can all be blank for a genuine grandMA2 onPC uninstall entry — only
    DisplayName ("grandMA2 onPC 3.9.60.91") reliably carries the version,
    and matching it via Where-Object is itself the identity signal."""
    fake_output = (
        "grandMA2 onPC 3.9.60.91|\n"
        "grandMA2 onPC 3.9.63.6|\n"
    )
    monkeypatch.setattr(ma_default_dirs, "_run_powershell", lambda *_a, **_k: fake_output)
    assert _registry_ma2_versions_windows() == ("3.9.60.91", "3.9.63.6")


def test_registry_scan_prefers_exe_version_when_present(monkeypatch) -> None:
    fake_output = "grandMA2 onPC 3.9.60|3.9.60.91\n"
    monkeypatch.setattr(ma_default_dirs, "_run_powershell", lambda *_a, **_k: fake_output)
    assert _registry_ma2_versions_windows() == ("3.9.60.91",)


def test_shortcut_scan_rejects_open_show_folder_explorer_target(monkeypatch) -> None:
    """Regression test for the exact false positive reported: an "Open Show
    Folder grandMA2 onPC 3.9.60.91.lnk" shortcut (name matches the filter)
    targeting C:\\Windows\\explorer.exe must not contribute a version,
    while the real launch shortcut for the same install must."""
    fake_output = (
        "grandMA2 onPC 3.9.60.91.lnk|C:\\Program Files\\MA Lighting Technologies\\grandma\\grandMA2 onPC 3.9.60.91\\gma2onpc.exe\n"
        "grandMA2 onPC 3.9.60.91 CleanStart.lnk|C:\\Program Files\\MA Lighting Technologies\\grandma\\grandMA2 onPC 3.9.60.91\\gma2onpc.exe\n"
        "Open Show Folder grandMA2 onPC 3.9.60.91.lnk|C:\\Windows\\explorer.exe\n"
    )
    monkeypatch.setattr(ma_default_dirs, "_run_powershell", lambda *_a, **_k: fake_output)
    assert _shortcut_ma2_versions_windows() == ("3.9.60.91", "3.9.60.91")


def test_full_build_maps_to_matching_importexport(tmp_path: Path) -> None:
    expected = tmp_path / "gma2_V_3.9.63" / "importexport"
    expected.mkdir(parents=True)
    installs = discover_ma2_installations(tmp_path)
    assert ma2_export_dir_for_version("3.9.63.6", installs) == expected
    assert ma2_export_dir_for_version("3.9.61", installs) is None
    assert ma2_version_from_path(expected) == "3.9.63"
    assert ma2_version_from_path(tmp_path / "custom") is None


def test_resolve_rejects_cross_console_remembered(tmp_path: Path) -> None:
    ma2ish = tmp_path / "MA Lighting Technologies" / "grandma" / "gma2_V_3.9" / "importexport"
    ma2ish.mkdir(parents=True)
    # Remembered MA2 path must not stick when resolving MA3.
    result = resolve_export_dir("ma3", str(ma2ish))
    detected = default_ma3_export_dir()
    if detected is not None:
        assert result == str(detected)
    else:
        assert result == ""


def test_resolve_ma3_datapool_dirs(tmp_path: Path) -> None:
    from cueplayer.exporters.ma3 import resolve_ma3_datapool_dirs

    library = tmp_path / "gma3_library"
    library.mkdir()
    seq, tc, macros, views = resolve_ma3_datapool_dirs(library)
    assert seq == library / "datapools" / "sequences"
    assert tc == library / "datapools" / "timecodes"
    assert macros == library / "datapools" / "macros"
    # Views are a different library category — real hardware confirmed
    # they live under userprofiles/views, not datapools/views.
    assert views == library / "userprofiles" / "views"

    datapools = library / "datapools"
    datapools.mkdir()
    seq2, tc2, macros2, views2 = resolve_ma3_datapool_dirs(datapools)
    assert seq2 == datapools / "sequences"
    assert tc2 == datapools / "timecodes"
    assert macros2 == datapools / "macros"
    assert views2 == library / "userprofiles" / "views"


def test_resolve_ma2_pool_dirs(tmp_path: Path) -> None:
    from cueplayer.exporters.ma_default_dirs import resolve_ma2_pool_dirs

    importexport = tmp_path / "gma2_V_3.9.61" / "importexport"
    importexport.mkdir(parents=True)
    ie, plugins, macros = resolve_ma2_pool_dirs(importexport)
    assert ie == importexport
    assert plugins == importexport.parent / "plugins"
    assert macros == importexport.parent / "macros"

    library = tmp_path / "gma2_V_3.9.63"
    library.mkdir()
    ie2, plugins2, macros2 = resolve_ma2_pool_dirs(library)
    assert ie2 == library / "importexport"
    assert plugins2 == library / "plugins"
    assert macros2 == library / "macros"

    custom = tmp_path / "exports"
    custom.mkdir()
    ie3, plugins3, macros3 = resolve_ma2_pool_dirs(custom)
    assert ie3 == plugins3 == macros3 == custom


def test_ma2_show_install_goes_to_plugins(tmp_path: Path) -> None:
    from cueplayer.domain.models import MaExportSettings, Project
    from cueplayer.exporters.ma2 import Ma2Exporter
    from cueplayer.exporters.show_patch import build_show_patch, plans_from_show_patch
    from tests.exporters.test_show_patch import _song_with_buttons

    importexport = tmp_path / "gma2_V_3.9.61" / "importexport"
    importexport.mkdir(parents=True)

    project = Project.create("Show")
    project.songs = [_song_with_buttons("Song", ma="SongA", button_names=["Hit"])]
    settings = MaExportSettings(console="ma2", export_mode="full")
    slots = build_show_patch(project.songs, settings)
    plans = plans_from_show_patch(slots, settings)
    paths = Ma2Exporter().export_show_to_directory(
        plans, importexport, show_install_name="Show_Install"
    )

    assert paths["show:plugin_xml"].parent.name == "plugins"
    assert paths["show:plugin_lua"].parent.name == "plugins"
    assert paths["show:macro_xml"].parent.name == "macros"
    assert paths["SongA:main_sequence"].parent.name == "importexport"
    assert paths["show:plugin_xml"].is_file()
    lua = paths["show:plugin_lua"].read_text(encoding="utf-8")
    assert "At Timecode" in lua
    assert "Store Sequence" in lua

