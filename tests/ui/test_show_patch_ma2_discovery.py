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


def test_five_page_playlist_workflow_and_screen3_grid(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    page = ShowPatchPage()
    page.set_project(Project.create("Show"))

    assert page.workflow_tabs.count() == 5
    assert [page.workflow_tabs.tabText(i) for i in range(5)] == [
        "1  Songs & Pools",
        "2  Export Registry",
        "3  Console Setup",
        "4  View Layout",
        "5  Review & Export",
    ]
    assert page.view_stage.widgets[0]["type"] == "sequence"
    assert page.view_stage.widgets[0]["w"] == 10
    assert page.view_stage.widgets[2]["type"] == "effects"
    assert page.view_stage.widgets[2]["stride"] == 100
    assert page.registry_table.rowCount() == 1
    assert page.review_table.rowCount() == 1
    assert page.playlist_table.rowCount() == 1
    assert page.playlist_table.columnCount() == 9
    assert page.registry_command_port.value() == 30000
    assert page.registry_monitor_port.value() == 30001
    assert page.registry_version.text() == "3.9.63.6"
    page.workflow_tabs.setCurrentIndex(4)
    assert page.workflow_tabs.currentWidget() is page.review_page


def test_view_allocation_controls_drive_shared_export_settings(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)

    page.view_stage.selected_index = 0
    page._load_view_inspector(0)
    page.view_pool_number_start.setValue(301)
    page.view_pool_stride.setValue(30)
    page.view_stage.selected_index = 2
    page._load_view_inspector(2)
    page.view_pool_number_start.setValue(501)
    page.view_pool_stride.setValue(125)
    page.view_pool_x.setValue(2)
    page.view_pool_width.setValue(12)
    page.ma2_view_pool_start.setValue(401)

    assert project.ma_export.sequence_pool_start == 301
    assert project.ma_export.ma2_sequence_slots_per_song == 30
    assert project.ma_export.ma2_effect_pool_start == 501
    assert project.ma_export.ma2_effect_slots_per_song == 125
    assert project.ma_export.ma2_view_pool_start == 401
    assert page.seq_start.value() == 301
    assert page.ma2_effect_slots.value() == 125
    assert project.ma_export.ma2_view_layout[2]["start"] == 501
    assert project.ma_export.ma2_view_layout[2]["stride"] == 125
    assert project.ma_export.ma2_view_layout[2]["x"] == 2
    assert project.ma_export.ma2_view_layout[2]["w"] == 12

    before = len(page.view_stage.widgets)
    page._duplicate_view_pool()
    assert len(page.view_stage.widgets) == before + 1
    page._delete_view_pool()
    assert len(page.view_stage.widgets) == before


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
