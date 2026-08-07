"""Tests for MA default export directory detection."""

from __future__ import annotations

from pathlib import Path

from cueplayer.exporters.ma_default_dirs import (
    discover_ma2_environment,
    discover_ma2_installations,
    default_ma2_export_dir,
    default_ma3_export_dir,
    ma2_export_dir_for_version,
    ma2_version_from_path,
    ma2_version_supported,
    resolve_export_dir,
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
    discovery = discover_ma2_environment(tmp_path, lambda: "3.9.63.6")
    assert discovery.running_version == "3.9.63.6"
    assert discovery.recommended_version == "3.9.63.6"


def test_discovery_falls_back_to_newest_supported_install(tmp_path: Path) -> None:
    for name in ("gma2_V_3.2.2", "gma2_V_3.3.4", "gma2_V_3.9.60"):
        (tmp_path / name / "importexport").mkdir(parents=True)
    discovery = discover_ma2_environment(tmp_path, lambda: None)
    assert discovery.recommended_version == "3.9.60"
    assert not ma2_version_supported("3.3.4.2")
    assert ma2_version_supported("3.3.4.3")


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
    seq, tc, macros = resolve_ma3_datapool_dirs(library)
    assert seq == library / "datapools" / "sequences"
    assert tc == library / "datapools" / "timecodes"
    assert macros == library / "datapools" / "macros"

    datapools = library / "datapools"
    datapools.mkdir()
    seq2, tc2, macros2 = resolve_ma3_datapool_dirs(datapools)
    assert seq2 == datapools / "sequences"
    assert tc2 == datapools / "timecodes"
    assert macros2 == datapools / "macros"


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

