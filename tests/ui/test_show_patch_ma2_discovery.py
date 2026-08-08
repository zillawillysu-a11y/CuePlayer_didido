"""Production MA2 version/folder and Registry-to-Setup UI behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
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


def test_console_setup_fits_a_maximized_1920x1080_window_without_page_scroll(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Console Setup is hosted in a QScrollArea (fallback for genuinely
    small windows), but at a normal maximized desktop size it must not
    need to actually scroll — regression test for the reflow that cut its
    natural height from 739px to ~524px (4/2-column grids instead of
    1/2-column QFormLayout/QGridLayout rows). 524 leaves real headroom
    below any plausible viewport at 1920x1080 after toolbar/transport/tab
    chrome, even allowing for real Windows font metrics being taller than
    this environment's offscreen fallback font."""
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)
    page.resize(1920, 1040)
    page.show()
    page.workflow_tabs.setCurrentIndex(2)
    app.processEvents()
    app.processEvents()

    setup_area = page.workflow_tabs.widget(2)
    assert page.setup_page.sizeHint().height() < 650
    # The fallback QScrollArea itself must still be there for small windows.
    from PySide6.QtWidgets import QScrollArea

    assert isinstance(setup_area, QScrollArea)
    page.close()


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


def test_target_version_dropdown_lists_every_real_installed_patch_full_precision(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression test for the bug report: multiple grandMA2 onPC point
    releases installed at once (3.9.60.18/.74/.89/.91) must all appear in
    the Target Version dropdown with their full 4-segment number — and no
    generic/truncated "3.9.60" entry may appear alongside them."""
    discovery = Ma2Discovery(
        installations=(),
        running_version=None,
        installed_versions=(
            "3.1.2.5", "3.3.4.3", "3.7.0.1", "3.7.0.5", "3.8.0.0", "3.9.0.3",
            "3.9.60.18", "3.9.60.74", "3.9.60.89", "3.9.60.91", "3.9.61.5", "3.9.63.6",
        ),
    )
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment", lambda: discovery
    )
    page = ShowPatchPage()
    page.set_project(Project.create("Show"))

    items = [page.ma2_version.itemText(i) for i in range(page.ma2_version.count())]
    for expected in discovery.installed_versions:
        assert expected in items, f"{expected} missing from dropdown: {items}"
    # No collapsed/generic 3-segment duplicate for a family that has a real
    # 4-segment version present.
    assert "3.9.60" not in items
    assert "3.9.61" not in items
    assert "3.9.63" not in items
    # Highest supported real version wins as the recommendation.
    assert page.ma2_version.currentText() == "3.9.63.6"
    # The right-side "Running X · Installed Y, Z, ..." summary was removed
    # (a supported version leaves the status label blank).
    assert page.ma2_detect_status.text() == ""


def test_detect_ma2_summary_removed_but_controls_and_warning_kept(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The Detect MA2 right-side "Running X · Installed Y, Z, ..." summary
    is gone, but the console radios, Target Version dropdown, Detect MA2
    button, and the unsupported-version warning all remain."""
    discovery = Ma2Discovery(installations=(), running_version=None, installed_versions=())
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment", lambda: discovery
    )
    project = Project.create("Show")
    project.ma_export.ma2_target_version = "2.9.99.9"
    page = ShowPatchPage()
    page.set_project(project)

    assert page.ma2_radio is not None
    assert page.ma3_radio is not None
    assert page.ma2_version.count() > 0
    assert page.ma2_detect_btn is not None
    # An unsupported version still produces a warning — only the
    # always-shown "Running/Installed" dump was removed, not this label.
    assert "Unsupported" in page.ma2_detect_status.text()


def test_set_project_with_same_object_does_not_rediscover_ma2(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression test for the Exporter view-switch latency bug: repeated
    set_project() calls with the *same* project object (exactly what
    MainWindow._set_view_mode does on every Timeline<->Exporter switch)
    must not re-run discover_ma2_environment() — that call shells out to
    three sequential PowerShell subprocesses and measured ~2.5-2.9s on
    real hardware. Only a genuinely different project object should."""
    calls = []
    discovery_result = _discovery(tmp_path)

    def fake_discover():
        calls.append(1)
        return discovery_result

    monkeypatch.setattr("cueplayer.ui.show_patch_page.discover_ma2_environment", fake_discover)
    page = ShowPatchPage()
    project = Project.create("Show")

    page.set_project(project)
    assert len(calls) == 1, "first bind must discover once"

    # Simulate several Exporter view-switches with the identical project.
    page.set_project(project)
    page.set_project(project)
    page.set_project(project)
    assert len(calls) == 1, "same project object must not re-trigger discovery"

    # A genuinely new/reloaded project must discover again exactly once.
    other_project = Project.create("Show 2")
    page.set_project(other_project)
    assert len(calls) == 2, "a different project object must re-discover"

    page.set_project(other_project)
    assert len(calls) == 2, "still cached for the new project's repeat calls"


def test_set_project_same_object_still_refreshes_data(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The fast (no-discovery) path must still pick up project changes made
    elsewhere while Exporter was hidden — e.g. a setting edited on another
    page, or a song added to the Export Queue."""
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    page = ShowPatchPage()
    project = Project.create("Show")
    page.set_project(project)
    assert page.show_name.text() == "CuePlayer"
    assert page.song_pick.count() == 0

    project.ma_export.ma2_show_name = "Changed Elsewhere"
    project.ma_export.export_song_ids = [project.songs[0].id]
    page.set_project(project)  # same object, second call — no discovery, but must resync

    assert page.show_name.text() == "Changed Elsewhere"
    assert page.song_pick.count() == 1


def test_detect_ma2_button_always_forces_fresh_discovery(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Detect MA2 must always re-run a full discovery, even right after a
    same-object set_project() call skipped it — it must never return stale
    cache silently."""
    calls = []

    def fake_discover():
        calls.append(1)
        return _discovery(tmp_path)

    monkeypatch.setattr("cueplayer.ui.show_patch_page.discover_ma2_environment", fake_discover)
    page = ShowPatchPage()
    project = Project.create("Show")
    page.set_project(project)
    page.set_project(project)
    page.set_project(project)
    assert len(calls) == 1

    page.ma2_detect_btn.click()
    assert len(calls) == 2, "Detect MA2 must force a fresh discovery regardless of caching"

    page.ma2_detect_btn.click()
    assert len(calls) == 3, "Detect MA2 must re-discover every time it's pressed"


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
    assert page.playlist_table.columnCount() == 11
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


def test_live_scan_section_text_has_no_stray_dark_background(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """MA2 Live Pool Scan's title and field labels ("MA2 Host", "Target
    Version", "Command", "Monitor", "MA2 Show User", "Password", "Plugin
    Pool", "MA2 Plugin Import Path") must render on the panel background,
    not an extra dark rectangle. QGroupBox::title needs an explicit
    "background: transparent" — Windows' native groupbox chrome paints an
    opaque theme background behind the title sub-control otherwise, even
    though the rest of the box already uses a custom stylesheet."""
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    page = ShowPatchPage()
    page.set_project(Project.create("Show"))

    assert "QGroupBox::title" in page.styleSheet()
    title_rule = page.styleSheet().split("QGroupBox::title", 1)[1].split("}", 1)[0]
    assert "background: transparent" in title_rule

    for widget in (
        page.registry_host,
        page.registry_version,
        page.registry_command_port,
        page.registry_monitor_port,
        page.registry_user,
        page.registry_password,
        page.registry_plugin_pool,
    ):
        field_widget = widget.parentWidget()
        assert field_widget.objectName() == "maLiveScanField"


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
    content = page.playlist_table.cellWidget(0, 10)
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
    assert page.playlist_table.cellWidget(0, 10).text() == "0/3 selected"
    page._select_all_content(song.id)
    assert project.ma_export.export_content_by_song[song.id] == {
        "main": True,
        "buttons": [2, 3],
    }
    assert page.playlist_table.cellWidget(0, 10).text() == "3/3 selected"


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

    # review_macro_checks follows _EXPORT_CONTENT_CHECK_LABELS order:
    # Song List Sequence, Fixed control Macros, Song Macro, Song View, Preset.
    page.review_macro_checks[1].setChecked(True)
    assert page.ma2_fixed_macros.isChecked()
    page.ma2_song_macros.setChecked(True)
    assert page.review_macro_checks[2].isChecked()
    assert page.review_pool_start_fields["view_start"].toolTip()
    assert page.review_table.item(0, 5).text() == "1–20"

    paths = page._write_export_allocation_report(tmp_path)
    # The CSV report is no longer auto-written alongside the MA files — it is
    # now a standalone Save As action (_export_allocation_report_csv) so it
    # never lands in the MA2 import/export folder unasked. The TXT summary
    # still writes here for a quick alongside-the-export record.
    assert "show:allocation_csv" not in paths
    assert paths["show:allocation_txt"].exists()
    assert "Groups" in paths["show:allocation_txt"].read_text(encoding="utf-8")


def test_allocation_report_columns_include_export_name_and_page(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    project.songs[0].name = "第一首"
    project.songs[0].ma_export_name = "FirstSong"
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([project.songs[0].id])

    columns, rows = page._allocation_report_columns_and_rows()
    assert columns == [
        "Order", "Song", "Export Name", "Sequence", "Effects", "Groups",
        "Timecode", "View", "Page", "Song Macro",
    ]
    assert rows[0]["Song"] == "第一首"
    assert rows[0]["Export Name"] == "FirstSong"
    assert rows[0]["Page"] == str(page._slots[0].page)


def test_csv_report_default_directory_follows_project_file_then_falls_back(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)

    # No provider / unsaved project: falls back to a Documents-style path,
    # never the MA2 output folder.
    fallback = page._default_allocation_report_directory()
    assert str(fallback) != str(page.out_dir.text())

    project_dir = tmp_path / "MyShows"
    project_dir.mkdir()
    project_file = project_dir / "MyShow.cueproj"
    page.project_file_path_provider = lambda: project_file
    assert page._default_allocation_report_directory() == project_dir


def test_export_csv_button_opens_save_dialog_and_writes_chosen_path(
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

    chosen = tmp_path / "custom name.csv"
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(chosen), "CSV Files (*.csv)"),
    )
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.QMessageBox.information",
        lambda *args, **kwargs: None,
    )

    page._export_allocation_report_csv()

    assert chosen.exists()
    text = chosen.read_text(encoding="utf-8-sig")
    assert "Export Name" in text and "Page" in text


def test_export_csv_button_does_nothing_when_dialog_is_cancelled(
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

    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    before = list(tmp_path.iterdir())
    page._export_allocation_report_csv()
    assert list(tmp_path.iterdir()) == before


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
    txt_text = paths["show:allocation_txt"].read_text(encoding="utf-8")
    assert txt_text.index("Second") < txt_text.index("First")


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
    page.review_pool_start_fields["seq_start"].setValue(301)
    page._auto_fill_pool_overrides()
    assert project.ma_export.ma2_pool_overrides

    page._clear_pool_overrides()

    assert project.ma_export.ma2_pool_overrides == {}


def test_manual_pool_start_seeds_start_blank_and_blank_pools_are_untouched(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A blank seed means "leave this Pool alone", so filling only Timecode
    renumbers just the Timecode column."""
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

    # Seeds start blank (0) and must stay blank across a refresh.
    assert all(field.value() == 0 for field in page.review_pool_start_fields.values())
    page.refresh()
    assert all(field.value() == 0 for field in page.review_pool_start_fields.values())

    before = [
        (s.main_sequence, s.effect_start, s.group_start, s.view_pool, s.song_macro_pool)
        for s in page._slots
    ]
    page.review_pool_start_fields["timecode_start"].setValue(500)
    page._auto_fill_pool_overrides()

    assert [slot.timecode_pool for slot in page._slots] == [500, 501, 502]
    after = [
        (s.main_sequence, s.effect_start, s.group_start, s.view_pool, s.song_macro_pool)
        for s in page._slots
    ]
    assert after == before, "blank Pools must not be renumbered"
    for song in project.songs:
        assert set(project.ma_export.ma2_pool_overrides[song.id]) == {"timecode"}


def test_auto_fill_with_every_seed_blank_changes_nothing(
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

    assert project.ma_export.ma2_pool_overrides == {}
    assert "every Manual Pool Start is blank" in page.registry_scan_status.text()


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


def test_registry_and_review_have_separate_order_song_and_export_name_columns(
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

    assert [
        page.registry_table.horizontalHeaderItem(i).text() for i in range(3)
    ] == ["Order", "Song", "Export Name"]
    assert [
        page.review_table.horizontalHeaderItem(i).text() for i in range(3)
    ] == ["Order", "Song", "Export Name"]

    # Export Registry has no other order column, so Order carries the
    # setlist number; Review's Order is the export queue position.
    assert page.registry_table.item(0, 0).text() == "1"
    assert page.registry_table.item(0, 1).text() == "真罕得想起來"
    assert page.registry_table.item(0, 2).text() == "Rarely_Think_of_It"
    assert page.review_table.item(0, 0).text() == "1"
    assert page.review_table.item(0, 1).text() == "真罕得想起來"
    assert page.review_table.item(0, 2).text() == "Rarely_Think_of_It"


def test_song_column_falls_back_to_the_english_name_when_there_is_no_chinese(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A song named only in English (e.g. 88Bars) must still show its name in
    the Song column — never a blank cell."""
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show", with_song=False)
    song = Song.create("88Bars")
    song.ma_export_name = "88Bars"
    project.songs.append(song)
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([song.id])

    assert page.registry_table.item(0, 1).text() == "88Bars"
    assert page.registry_table.item(0, 2).text() == "88Bars"
    assert page.review_table.item(0, 1).text() == "88Bars"
    assert page.review_table.item(0, 2).text() == "88Bars"


@pytest.mark.parametrize("window_height", [900, 700, 560, 440])
def test_manual_pool_start_rows_never_overlap(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    window_height: int,
) -> None:
    """Geometry regression guard for the Manual Pool Starts overlap.

    This bug survived three separate layout rewrites because it was only ever
    checked by eye. Root cause (confirmed by controlled experiment): a
    word-wrapped QLabel above the fields under-reports its height-for-width,
    so the parent under-allocates and QFormLayout compresses the row pitch
    (25px) below the height each spinbox actually paints at (38px) — 13px of
    overlap per row. Assert real rendered geometry so it cannot silently
    return; keep wrapped labels out of that column.
    """
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show", with_song=False)
    for name in ("真罕得想起來", "88Bars"):
        song = Song.create(name)
        song.ma_export_name = "Song_" + str(len(project.songs))
        project.songs.append(song)
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([song.id for song in project.songs])
    page.workflow_tabs.setCurrentIndex(4)  # Review & Export
    page.resize(1600, window_height)
    page.show()
    try:
        for _ in range(3):
            app.processEvents()

        rows = []
        for attr in (
            "seq_start", "effect_start", "timecode_start",
            "group_start", "macro_start", "view_start",
        ):
            field = page.review_pool_start_fields[attr]
            top = field.mapToGlobal(field.rect().topLeft()).y()
            rows.append((attr, top, field.height()))
        rows.sort(key=lambda row: row[1])

        for name, _top, height in rows:
            assert height >= 20, f"{name} spinbox crushed to {height}px"
        for (upper, upper_top, upper_height), (lower, lower_top, _h) in zip(rows, rows[1:]):
            assert lower_top >= upper_top + upper_height, (
                f"{upper} overlaps {lower} by "
                f"{upper_top + upper_height - lower_top}px at window height {window_height}"
            )
    finally:
        page.close()


def test_scan_result_also_moves_the_group_pool(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Groups was omitted from apply_registry_scan_result, so a scan left the
    Group Pool pointing at numbers the console was already using."""
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([project.songs[0].id])

    assert page.apply_registry_scan_result(
        remote_version="3.9.63.6",
        sequence_start=509,
        effect_start=7999,
        timecode_start=38,
        song_macro_start=362,
        view_start=250,
        group_start=403,
    )

    assert page.ma2_group_pool_start.value() == 403
    assert project.ma_export.ma2_group_pool_start == 403
    assert page._slots[0].group_start == 403


def test_scan_result_also_moves_the_page_pool(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Page is a full allocation Pool too: a scan must move the Console
    Setup Page Executor field past whatever the console already has."""
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([project.songs[0].id])

    assert page.apply_registry_scan_result(
        remote_version="3.9.63.6",
        sequence_start=509,
        effect_start=7999,
        timecode_start=38,
        song_macro_start=362,
        view_start=250,
        group_start=403,
        page_start=13,
    )

    assert page.executor_page.value() == 13
    assert project.ma_export.main_executor.startswith("13.")
    assert page._slots[0].page == 13


def test_start_after_scanned_toggle_moves_every_pool_and_reverts(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show", with_song=False)
    for name in ("A", "B"):
        song = Song.create(name)
        song.ma_export_name = name
        project.songs.append(song)
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([song.id for song in project.songs])

    # Pin everything low, exactly as a stale Auto-Fill would.
    for field in page.review_pool_start_fields.values():
        field.setValue(201)
    page._auto_fill_pool_overrides()
    assert page._slots[0].main_sequence == 201

    scanned = {
        "sequence": 508, "effect": 7998, "timecode": 37,
        "macro": 361, "view": 249, "group": 402,
    }
    project.ma_export.ma2_scanned_pool_max = dict(scanned)
    page.refresh()
    # Pins still win while the toggle is off — and the UI must say so.
    assert page._slots[0].main_sequence == 201
    assert "pinned by manual overrides" in page.registry_status.text()

    page.registry_start_after_scanned.setChecked(True)

    assert project.ma_export.ma2_start_after_scanned is True
    for slot in page._slots:
        assert slot.main_sequence > scanned["sequence"]
        assert slot.effect_start > scanned["effect"]
        assert slot.group_start > scanned["group"]
        assert slot.timecode_pool > scanned["timecode"]
        assert slot.view_pool > scanned["view"]
        assert slot.song_macro_pool > scanned["macro"]

    page.registry_start_after_scanned.setChecked(False)
    assert project.ma_export.ma2_start_after_scanned is False
    # Ticking the toggle cleared the stale pins (that is what let every Pool
    # move), so switching it off returns to the configured starts rather than
    # to the old 201 pins.
    assert page._slots[0].main_sequence == int(project.ma_export.sequence_pool_start)


def _scanned_page(page, project):
    project.ma_export.ma2_scanned_pool_max = {
        "sequence": 508, "effect": 7998, "timecode": 37,
        "macro": 361, "view": 249, "group": 402,
    }
    page.refresh()


def test_start_after_scanned_checkbox_mirrored_on_both_pages(
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
    _scanned_page(page, project)

    page.registry_start_after_scanned.setChecked(True)
    assert page.review_start_after_scanned.isChecked() is True
    assert project.ma_export.ma2_start_after_scanned is True

    # Toggling the Review & Export copy drives the Export Registry one.
    page.review_start_after_scanned.setChecked(False)
    assert page.registry_start_after_scanned.isChecked() is False
    assert project.ma_export.ma2_start_after_scanned is False


def test_manual_edit_made_while_start_after_scanned_survives_switching_it_off(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The user's manual number must not snap back when the toggle goes off."""
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show", with_song=False)
    for name in ("A", "B", "C"):
        song = Song.create(name)
        song.ma_export_name = name
        project.songs.append(song)
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([song.id for song in project.songs])
    _scanned_page(page, project)

    page.registry_start_after_scanned.setChecked(True)
    assert page._slots[0].main_sequence == 509  # scanned max + 1

    page.review_table.item(1, 3).setText("700")  # pin song B's Sequence
    assert page._slots[1].main_sequence == 700

    page.review_start_after_scanned.setChecked(False)

    assert page._slots[1].main_sequence == 700, "manual edit bounced back"


def test_auto_fill_wins_over_start_after_scanned_and_switches_it_off(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show", with_song=False)
    for name in ("A", "B", "C"):
        song = Song.create(name)
        song.ma_export_name = name
        project.songs.append(song)
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([song.id for song in project.songs])
    _scanned_page(page, project)

    page.registry_start_after_scanned.setChecked(True)
    assert page._slots[0].main_sequence == 509

    page.review_pool_start_fields["seq_start"].setValue(100)
    page._auto_fill_pool_overrides()

    assert [slot.main_sequence for slot in page._slots] == [100, 120, 140]
    assert project.ma_export.ma2_start_after_scanned is False
    assert page.registry_start_after_scanned.isChecked() is False
    assert page.review_start_after_scanned.isChecked() is False


def test_ticking_start_after_scanned_clears_stale_pins_so_it_can_move(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show", with_song=False)
    for name in ("A", "B"):
        song = Song.create(name)
        song.ma_export_name = name
        project.songs.append(song)
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([song.id for song in project.songs])
    page.review_pool_start_fields["seq_start"].setValue(201)
    page._auto_fill_pool_overrides()
    assert page._slots[0].main_sequence == 201
    _scanned_page(page, project)

    page.registry_start_after_scanned.setChecked(True)

    assert project.ma_export.ma2_pool_overrides == {}
    assert page._slots[0].main_sequence == 509
    assert "cleared" in page.registry_scan_status.text()


def test_following_view_pool_tracks_the_live_allocation_not_just_console_setup(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """"Follow Console Setup" must also track whatever changes the numbers
    downstream of Console Setup: Start after scanned Pools, Auto-Fill, and a
    manual per-song edit in Review & Export."""
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show", with_song=False)
    for name in ("A", "B", "C"):
        song = Song.create(name)
        song.ma_export_name = name
        project.songs.append(song)
    page = ShowPatchPage()
    page.set_project(project)
    page._add_songs_to_export_queue([song.id for song in project.songs])

    page.view_stage.selected_index = 0  # DEFAULT_VIEW_LAYOUT[0] is "sequence"
    page._load_view_inspector(0)
    page.view_pool_follow.setChecked(True)

    def view_start() -> int:
        return int(page.view_stage.widgets[0]["start"])

    # 1) Start after scanned Pools
    project.ma_export.ma2_scanned_pool_max = {
        "sequence": 508, "effect": 7998, "timecode": 37,
        "macro": 361, "view": 249, "group": 402,
    }
    page.refresh()
    page.registry_start_after_scanned.setChecked(True)
    assert view_start() == page._slots[0].main_sequence == 509

    # 2) Auto-Fill
    page.review_pool_start_fields["seq_start"].setValue(100)
    page._auto_fill_pool_overrides()
    assert view_start() == page._slots[0].main_sequence == 100

    # 3) Manual per-song edit
    page.review_table.item(0, 3).setText("640")
    assert view_start() == page._slots[0].main_sequence == 640

    # 4) Unticking Follow releases it again — later changes must not move it.
    page.view_stage.selected_index = 0
    page._load_view_inspector(0)
    page.view_pool_follow.setChecked(False)
    page.view_pool_number_start.setValue(42)
    page.review_table.item(0, 3).setText("900")
    assert view_start() == 42


@pytest.mark.parametrize("width,height", [(1920, 1040), (1600, 900), (1280, 700)])
def test_manual_pool_starts_fields_never_overlap(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, width: int, height: int
) -> None:
    """The 7 Pool Start spinboxes (Sequence/Effect/Timecode/Group/Macro/View/
    Page) must form a stable two-column grid: same x, same width, same
    height, and no pair may ever overlap — regression test for the
    QFormLayout squeeze bug where real Windows font metrics compressed rows
    into each other. Covers a maximized-1920x1080-ish window down to a
    short ~700px one, since the fields must never overlap regardless of
    window height."""
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.discover_ma2_environment",
        lambda: _discovery(tmp_path),
    )
    project = Project.create("Show")
    page = ShowPatchPage()
    page.set_project(project)
    page.resize(width, height)
    page.show()
    page.workflow_tabs.setCurrentIndex(4)
    app.processEvents()
    app.processEvents()

    order = [
        "seq_start", "effect_start", "timecode_start",
        "group_start", "macro_start", "view_start", "page_start",
    ]
    fields = [page.review_pool_start_fields[name] for name in order]
    tops = [f.mapTo(page, QPoint(0, 0)).y() for f in fields]
    xs = {f.mapTo(page, QPoint(0, 0)).x() for f in fields}
    widths = {f.width() for f in fields}
    heights = {f.height() for f in fields}

    assert len(xs) == 1, f"Pool Start fields must share one x, got {xs}"
    assert len(widths) == 1, f"Pool Start fields must share one width, got {widths}"
    assert len(heights) == 1, f"Pool Start fields must share one height, got {heights}"
    field_height = heights.pop()

    for name, top, next_name, next_top in zip(order, tops, order[1:], tops[1:]):
        bottom = top + field_height
        assert bottom < next_top, (
            f"{name} (bottom={bottom}) overlaps {next_name} (top={next_top}) "
            f"at {width}x{height}"
        )

    # Page (the last row) must never touch Auto-Fill & Sequence / Clear All
    # Overrides below it.
    page_bottom = tops[-1] + field_height
    autofill_top = page.review_autofill_btn.mapTo(page, QPoint(0, 0)).y()
    assert page_bottom < autofill_top, (
        f"Page row (bottom={page_bottom}) overlaps the button row "
        f"(top={autofill_top}) at {width}x{height}"
    )
    page.close()
