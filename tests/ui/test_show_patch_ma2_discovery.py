"""Production MA2 version/folder and Registry-to-Setup UI behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox

from cueplayer.domain.models import Project, Song
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

    assert page.workflow_tabs.count() == 4
    assert [page.workflow_tabs.tabText(i) for i in range(4)] == [
        "1  Songs & Pools",
        "2  Export Registry",
        "3  Console Setup & Review Export",
        "4  View Layout",
    ]
    assert page.view_stage.widgets[0]["type"] == "sequence"
    assert page.view_stage.widgets[0]["w"] == 10
    assert page.view_stage.widgets[2]["type"] == "effects"
    assert page.view_stage.widgets[2]["stride"] == 100
    assert page.registry_table.rowCount() == 1
    status_light = page.registry_table.cellWidget(0, 1)
    assert status_light is not None
    assert "●  Planned" in status_light.text()
    assert page.review_table.rowCount() == 1
    assert page.playlist_table.rowCount() == 2
    assert page.playlist_table.columnCount() == 9
    assert page.registry_command_port.value() == 30000
    assert page.registry_monitor_port.value() == 30001
    assert page.registry_version.text() == "3.9.63.6"
    page.workflow_tabs.setCurrentIndex(2)
    page.console_review_tabs.setCurrentIndex(1)
    assert page.console_review_tabs.currentWidget() is page.review_page


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


def test_fixed_macro_export_start_is_independent_of_view_macro_pool(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)

    # Fixed control Macros import at 191, while the Screen 3 Macro Pool can
    # independently display Macro 501.
    page.ma2_fixed_macro_start.setValue(191)
    page.view_stage.selected_index = 1
    page._load_view_inspector(1)
    page.view_pool_number_start.setValue(501)

    assert project.ma_export.ma2_fixed_macro_start == 191
    assert page.view_stage.widgets[1]["type"] == "macros"
    assert page.view_stage.widgets[1]["mode"] == "fixed"
    assert page.view_stage.widgets[1]["start"] == 501


def test_export_option_checkboxes_use_the_panel_background(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    page = ShowPatchPage()
    page.set_project(Project.create("Show"))

    assert "#maExportOptions QCheckBox { background: #15181d; }" in page.styleSheet()
    assert page.ma2_fixed_macros.parent().objectName() == "maExportOptions"


def test_timecode_pool_uses_three_cells_including_its_title(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    page = ShowPatchPage()
    page.set_project(Project.create("Show"))
    page.view_stage.widgets = [{"type": "timecode", "mode": "perSong", "x": 0, "y": 0, "w": 3, "h": 1, "start": 201, "stride": 1}]
    page.view_stage.selected_index = 0
    page._load_view_inspector(0)

    assert "2 built-in Timecode slots" in page.view_allocation_status.text()


def test_timecode_pool_layout_can_extend_beyond_its_three_cell_minimum(app: QApplication) -> None:
    from cueplayer.ui.ma2_view_layout import Ma2ViewLayoutStage

    stage = Ma2ViewLayoutStage()
    stage.set_layout(
        [{"type": "timecode", "mode": "fixed", "x": 14, "y": 2, "w": 7, "h": 3, "start": 1, "stride": 1}]
    )

    assert stage.widgets[0]["w"] == 7
    assert stage.widgets[0]["h"] == 3
    assert stage.widgets[0]["x"] == 9

    stage.set_layout(
        [{"type": "timecode", "mode": "fixed", "x": 0, "y": 2, "w": 1, "h": 1, "start": 1, "stride": 1}]
    )
    assert stage.widgets[0]["w"] == 3


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
    page.executor_page.setValue(201)
    page.main_executor_number.setValue(130)
    page.button_executor_number.setValue(101)

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
    assert page.executor_page.value() == 201
    assert page.main_executor_number.value() == 130
    assert page.button_executor_number.value() == 101
    assert project.ma_export.main_executor == "201.130"
    assert project.ma_export.button_executor_start == "201.101"


def test_live_scan_syncs_registry_only_after_a_valid_snapshot(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from cueplayer.exporters.ma2_telnet import Ma2PoolSnapshot

    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)
    page.registry_plugin_pool.setValue(5)

    captured: dict[str, object] = {}

    class Scanner:
        def scan(self, **kwargs):
            captured.update(kwargs)
            return Ma2PoolSnapshot(
                version="3.9.63.6",
                sequence=frozenset({1, 40}),
                effect=frozenset({201, 500}),
                timecode=frozenset({201, 203}),
                macro=frozenset({101, 203}),
                view=frozenset({201, 205}),
            )

    monkeypatch.setattr("cueplayer.ui.show_patch_page.Ma2TelnetScanner", lambda *_args, **_kwargs: Scanner())
    page._scan_ma2_show()

    assert page.seq_start.value() == 41
    assert page.ma2_effect_pool_start.value() == 501
    assert page.tc_start.value() == 204
    assert page.ma2_song_macro_start.value() == 204
    assert page.ma2_view_pool_start.value() == 206
    assert page.ma2_fixed_macro_start.value() == 101
    assert captured["plugin_pool"] == 5


def test_executor_page_and_numbers_build_shared_song_page(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)

    page.executor_page.setValue(401)
    page.main_executor_number.setValue(150)
    page.button_executor_number.setValue(110)

    assert project.ma_export.main_executor == "401.150"
    assert project.ma_export.button_executor_start == "401.110"


def test_playlist_content_selection_persists_and_updates_summary(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    song = Song.create("Song")
    song.add_mark(1, 1.0, "Main")
    song.add_mark(2, 2.0, "Hit")
    song.add_mark(3, 3.0, "Crash")
    project.songs = [song]
    page = ShowPatchPage()
    page.set_project(project)

    page._set_content_main(song.id, False)
    page._set_content_button(song.id, 2, False)

    assert project.ma_export.export_content_by_song[song.id] == {
        "main": False,
        "buttons": [3],
    }
    content = page.playlist_table.cellWidget(0, 8)
    assert content is not None
    assert content.text() == "1/3 selected"
    page._toggle_content_details(song.id)
    assert not page.playlist_table.isRowHidden(1)
    detail = page.playlist_table.cellWidget(1, 0)
    assert detail is not None
    assert [check.text() for check in detail.findChildren(QCheckBox)] == [
        "Main", "Mark 2", "Mark 3"
    ]
    page._clear_content_selection(song.id)
    assert project.ma_export.export_content_by_song[song.id] == {
        "main": False,
        "buttons": [],
    }
    assert page.playlist_table.item(0, 0).checkState().value == 2
    assert page.playlist_table.cellWidget(0, 8).text() == "0/3 selected"
    page._select_all_content(song.id)
    assert project.ma_export.export_content_by_song[song.id] == {
        "main": True,
        "buttons": [2, 3],
    }
    assert page.playlist_table.cellWidget(0, 8).text() == "3/3 selected"


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
