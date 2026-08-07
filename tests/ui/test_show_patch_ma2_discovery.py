"""Production MA2 version/folder and Registry-to-Setup UI behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.exporters.ma_default_dirs import Ma2Discovery, Ma2Installation
from cueplayer.ui.show_patch_page import ShowPatchPage


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _discovery(root: Path) -> Ma2Discovery:
    library = root / "gma2_V_3.9.63"
    importexport = library / "importexport"
    importexport.mkdir(parents=True)
    return Ma2Discovery(
        (Ma2Installation("3.9.63", library, importexport),),
        "3.9.63.6",
    )


def test_detected_running_version_drives_default_folder(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    discovery = _discovery(tmp_path)
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment", lambda: discovery
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)

    assert page.ma2_version.currentText() == "3.9.63.6"
    assert page.out_dir.text() == str(discovery.installations[0].importexport_dir)
    assert project.ma_export.ma2_output_dir_follows_version


def test_custom_unicode_folder_survives_detection(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    discovery = _discovery(tmp_path / "install")
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment", lambda: discovery
    )
    custom = tmp_path / "自訂匯出"
    custom.mkdir()
    project = Project.create("Show")
    project.ma_export.output_dir_ma2 = str(custom)
    project.ma_export.ma2_output_dir_follows_version = False
    page = ShowPatchPage()
    page.set_project(project)

    assert page.out_dir.text() == str(custom)
    assert not project.ma_export.ma2_output_dir_follows_version


def test_registry_sync_updates_allocations_but_preserves_fixed_controls(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    discovery = _discovery(tmp_path)
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment", lambda: discovery
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)
    page.ma2_fixed_macro_start.setValue(101)
    page.ma2_template_page.setValue(200)
    page.main_fader.setText("201.130")
    page.button_fader.setText("201.101")

    applied = page.apply_registry_scan_result(
        remote_version="3.9.63.6",
        sequence_start=41,
        effect_start=401,
        timecode_start=203,
        song_macro_start=203,
        view_start=203,
        host="127.0.0.1",
    )

    assert applied
    assert page.seq_start.value() == 41
    assert page.ma2_effect_pool_start.value() == 401
    assert page.tc_start.value() == 203
    assert page.ma2_song_macro_start.value() == 203
    assert page.ma2_view_pool_start.value() == 203
    assert page.ma2_fixed_macro_start.value() == 101
    assert page.ma2_template_page.value() == 200
    assert page.main_fader.text() == "201.130"
    assert page.button_fader.text() == "201.101"


def test_registry_sync_rejects_unsupported_remote_version(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)
    before = page.seq_start.value()

    assert not page.apply_registry_scan_result(
        remote_version="3.3.4.2",
        sequence_start=999,
        effect_start=999,
        timecode_start=999,
        song_macro_start=999,
        view_start=999,
    )
    assert page.seq_start.value() == before
