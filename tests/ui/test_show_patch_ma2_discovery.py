"""Production MA2 version/folder and Registry-to-Setup UI behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
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
    page._add_songs_to_export_queue([page._project.songs[0].id])

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
    status_light = page.registry_table.cellWidget(0, 3)
    assert status_light is not None
    assert "●  Planned" in status_light.text()
    assert page.review_table.rowCount() == 1
    assert page.playlist_table.rowCount() == 2
    assert page.playlist_table.columnCount() == 10
    assert page.playlist_table.horizontalHeaderItem(6).text() == "Groups"
    assert page.registry_table.horizontalHeaderItem(6).text() == "Groups"
    assert page.review_table.horizontalHeaderItem(5).text() == "Groups"
    assert page.registry_command_port.value() == 30000
    assert page.registry_monitor_port.value() == 30001
    assert page.registry_version.text() == "3.9.63.6"
    page.workflow_tabs.setCurrentIndex(4)
    assert page.workflow_tabs.currentWidget() is page.review_page


def test_view_pool_start_is_independent_of_console_setup_unless_following(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without "Follow", View Layout Pool Start/Stride are their own numbers —
    editing them must not silently rewrite Console Setup's Pool Start fields."""
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)
    original_seq_start = page.seq_start.value()
    original_effect_slots = page.ma2_effect_slots.value()

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

    assert project.ma_export.sequence_pool_start == original_seq_start
    assert project.ma_export.ma2_effect_slots_per_song == original_effect_slots
    assert project.ma_export.ma2_view_pool_start == 401
    assert page.seq_start.value() == original_seq_start
    assert page.ma2_effect_slots.value() == original_effect_slots
    assert project.ma_export.ma2_view_layout[2]["start"] == 501
    assert project.ma_export.ma2_view_layout[2]["stride"] == 125
    assert project.ma_export.ma2_view_layout[2]["x"] == 2
    assert project.ma_export.ma2_view_layout[2]["w"] == 12

    before = len(page.view_stage.widgets)
    page._duplicate_view_pool()
    assert len(page.view_stage.widgets) == before + 1
    page._delete_view_pool()
    assert len(page.view_stage.widgets) == before


def test_follow_checkbox_mirrors_console_setup_pool_start(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)

    page.seq_start.setValue(777)
    page.ma2_sequence_slots.setValue(15)
    page.view_stage.selected_index = 0  # DEFAULT_VIEW_LAYOUT[0] is a "sequence" Pool
    page._load_view_inspector(0)
    assert page.view_pool_follow.isEnabled()

    page.view_pool_follow.setChecked(True)

    widget = page.view_stage.widgets[0]
    assert widget["follow"] is True
    assert widget["mode"] == "perSong"
    assert widget["start"] == 777
    assert widget["stride"] == 15
    assert page.view_pool_number_start.isEnabled() is False

    # Changing Console Setup afterwards must keep the following Pool in sync.
    page.seq_start.setValue(888)
    page.refresh()
    assert page.view_stage.widgets[0]["start"] == 888

    # Unchecking releases it back to an independently editable number.
    page.view_pool_follow.setChecked(False)
    assert page.view_stage.widgets[0]["follow"] is False
    assert page.view_pool_number_start.isEnabled() is True
    page.view_pool_number_start.setValue(42)
    assert page.view_stage.widgets[0]["start"] == 42
    page.seq_start.setValue(999)
    page.refresh()
    assert page.view_stage.widgets[0]["start"] == 42


def test_follow_checkbox_only_available_for_console_pool_types(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    page = ShowPatchPage()
    page.set_project(Project.create("Show"))

    page.view_stage.widgets.append(
        {"type": "camera", "mode": "fixed", "x": 0, "y": 7, "w": 4, "h": 1, "start": 1, "stride": 1}
    )
    page.view_stage.selected_index = len(page.view_stage.widgets) - 1
    page._load_view_inspector(page.view_stage.selected_index)

    assert page.view_pool_follow.isEnabled() is False
    assert page.view_pool_follow.isChecked() is False


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

    assert "#maExportOptions QCheckBox { background: transparent; }" in page.styleSheet()
    assert "#reviewExportContent QCheckBox { background: transparent;" in page.styleSheet()
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
    page._add_songs_to_export_queue([song.id])

    page._set_content_main(song.id, False)
    page._set_content_button(song.id, 2, False)

    assert project.ma_export.export_content_by_song[song.id] == {
        "main": False,
        "buttons": [3],
    }
    content = page.playlist_table.cellWidget(0, 9)
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
    assert page.playlist_table.cellWidget(0, 9).text() == "0/3 selected"
    page._select_all_content(song.id)
    assert project.ma_export.export_content_by_song[song.id] == {
        "main": True,
        "buttons": [2, 3],
    }
    assert page.playlist_table.cellWidget(0, 9).text() == "3/3 selected"


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


def test_review_checks_sync_groups_and_export_allocation_report(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([project.songs[0].id])

    page.review_macro_checks[0].setChecked(True)
    assert page.ma2_fixed_macros.isChecked()
    page.ma2_song_macros.setChecked(True)
    assert page.review_macro_checks[1].isChecked()
    assert page.review_pool_start_fields["view_start"].toolTip()
    assert page.review_table.item(0, 5).text() == "1–20"

    paths = page._write_export_allocation_report(tmp_path)
    assert paths["show:allocation_csv"].exists()
    assert paths["show:allocation_txt"].exists()
    assert "Groups" in paths["show:allocation_csv"].read_text(encoding="utf-8-sig")


def test_clear_queue_button_empties_queue_and_settings(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    project.songs.append(Song.create("Second Song"))
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([song.id for song in project.songs])
    assert page.song_pick.count() == 2

    page.song_none_btn.click()

    assert page.song_pick.count() == 0
    assert project.ma_export.export_song_ids == []
    assert page._slots == []
    # A subsequent refresh (e.g. a settings edit) must not resurrect the
    # cleared queue from stale checkbox state.
    page.refresh()
    assert project.ma_export.export_song_ids == []


def test_export_queue_accepts_a_song_ids_drop_from_the_setlist_panel(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ExportQueueList must accept drops carrying EXPORT_SONG_IDS_MIME from any
    source widget — the Songs & Pools tab no longer has its own duplicate Set
    List tree; the real Setlist sidebar (SetlistWidget in main_window.py) is
    the only drag source now. See test_setlist_export_drag.py for coverage
    that SetlistWidget actually produces this payload for song and folder
    drags."""
    from PySide6.QtCore import QMimeData, QPointF
    from PySide6.QtGui import QDropEvent

    from cueplayer.ui.dnd_mime import EXPORT_SONG_IDS_MIME

    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show", with_song=False)
    for name in ("Opener", "Second", "Third"):
        project.songs.append(Song.create(name))
    page = ShowPatchPage()
    page.set_project(project)

    mime = QMimeData()
    mime.setData(
        EXPORT_SONG_IDS_MIME,
        "\n".join(song.id for song in project.songs).encode("utf-8"),
    )
    event = QDropEvent(
        QPointF(4, 4),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    page.song_pick.dropEvent(event)

    assert [
        page.song_pick.item(row).data(Qt.ItemDataRole.UserRole)
        for row in range(page.song_pick.count())
    ] == [song.id for song in project.songs]


def test_multi_select_drag_appends_without_duplicating_existing_queue(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show", with_song=False)
    for name in ("A", "B", "C"):
        project.songs.append(Song.create(name))
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([project.songs[0].id])

    # Multi-select B and C (and re-drag A, already queued) in one gesture.
    page._add_songs_to_export_queue([song.id for song in project.songs])

    queue_ids = [
        page.song_pick.item(row).data(Qt.ItemDataRole.UserRole)
        for row in range(page.song_pick.count())
    ]
    assert queue_ids == [song.id for song in project.songs]
    assert len(queue_ids) == len(set(queue_ids))


def test_reordering_export_queue_updates_order_everywhere(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show", with_song=False)
    for name in ("First", "Second"):
        project.songs.append(Song.create(name))
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([song.id for song in project.songs])
    assert [slot.display_name for slot in page._slots] == ["First", "Second"]

    # Simulate a drag reorder within the Export Queue: move row 1 above row 0.
    moved = page.song_pick.takeItem(1)
    page.song_pick.insertItem(0, moved)
    page._on_song_pick_changed()

    assert project.ma_export.export_song_ids == [
        project.songs[1].id,
        project.songs[0].id,
    ]
    assert [slot.display_name for slot in page._slots] == ["Second", "First"]

    paths = page._write_export_allocation_report(tmp_path)
    csv_text = paths["show:allocation_csv"].read_text(encoding="utf-8-sig")
    assert csv_text.index("Second") < csv_text.index("First")


def test_editing_a_review_table_pool_cell_stores_a_manual_override(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([project.songs[0].id])
    song_id = project.songs[0].id

    # Timecode column (6) currently shows the computed default.
    timecode_item = page.review_table.item(0, 6)
    assert timecode_item.text() == str(page._slots[0].timecode_pool)

    # setText() triggers the connected itemChanged signal synchronously,
    # which is what a real double-click edit in the app does too.
    timecode_item.setText("777")

    assert project.ma_export.ma2_pool_overrides[song_id]["timecode"] == 777
    assert page._slots[0].timecode_pool == 777
    assert page.review_table.item(0, 6).text() == "777"

    # Blanking the cell clears the override and falls back to the default.
    default_before_override = int(page._project.ma_export.timecode_pool_start)
    page.review_table.item(0, 6).setText("")
    assert "timecode" not in project.ma_export.ma2_pool_overrides.get(song_id, {})
    assert page._slots[0].timecode_pool == default_before_override


def test_review_table_highlights_colliding_pool_cells(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show", with_song=False)
    for name in ("First", "Second"):
        project.songs.append(Song.create(name))
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([song.id for song in project.songs])

    from PySide6.QtGui import QColor

    default_bg = page.review_table.item(0, 6).background().color()

    # Force both songs' Timecode onto the same number.
    target = str(page._slots[0].timecode_pool)
    page.review_table.item(1, 6).setText(target)

    first_bg = page.review_table.item(0, 6).background().color()
    second_bg = page.review_table.item(1, 6).background().color()
    assert first_bg == QColor("#7f1d1d")
    assert second_bg == QColor("#7f1d1d")
    assert first_bg != default_bg
    assert page.review_table.item(0, 6).toolTip()


def test_auto_fill_sequences_every_song_from_the_seed_fields(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show", with_song=False)
    for name in ("First", "Second", "Third"):
        project.songs.append(Song.create(name))
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([song.id for song in project.songs])

    page.review_pool_start_fields["timecode_start"].setValue(500)
    page.review_pool_start_fields["view_start"].setValue(600)
    page._auto_fill_pool_overrides()

    assert [slot.timecode_pool for slot in page._slots] == [500, 501, 502]
    assert [slot.view_pool for slot in page._slots] == [600, 601, 602]
    for song in project.songs:
        assert project.ma_export.ma2_pool_overrides[song.id]["timecode"]
        assert project.ma_export.ma2_pool_overrides[song.id]["view"]


def test_clear_all_overrides_button_removes_every_override(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([project.songs[0].id])
    page._auto_fill_pool_overrides()
    assert project.ma_export.ma2_pool_overrides

    page._clear_pool_overrides()

    assert project.ma_export.ma2_pool_overrides == {}


def test_manual_pool_override_reaches_playlist_and_registry_tables_too(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The override must show up everywhere, not just the Review table —
    Songs & Pools' playlist_table and Export Registry's registry_table both
    read from the same SongPatchSlot fields."""
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([project.songs[0].id])
    song_id = project.songs[0].id

    project.ma_export.ma2_pool_overrides[song_id] = {"effects": 999}
    page.refresh()

    assert page.playlist_table.item(0, 5).text().startswith("999")
    assert page.registry_table.item(0, 5).text().startswith("999")
    assert page.review_table.item(0, 4).text().startswith("999")


def test_registry_and_review_have_separate_order_chinese_and_song_columns(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show", with_song=False)
    song = Song.create("真罕得想起來")
    song.ma_export_name = "Rarely_Think_of_It"
    song.setlist_number = 1.0
    project.songs.append(song)
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([song.id])

    # Export Registry: Order / Chinese / Song are three separate columns —
    # it has no other Order column, so it carries the setlist number.
    assert page.registry_table.item(0, 0).text() == "1"
    assert page.registry_table.item(0, 1).text() == "真罕得想起來"
    assert page.registry_table.item(0, 2).text() == "Rarely_Think_of_It"
    # Review & Export already has its own Order column (export queue
    # position, column 0) — Chinese is a new column 1, Song stays column 2.
    assert page.review_table.item(0, 0).text() == "1"
    assert page.review_table.item(0, 1).text() == "真罕得想起來"
    assert page.review_table.item(0, 2).text() == "Rarely_Think_of_It"
