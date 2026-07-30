"""Set List Sheet rows + TSV for MA3 / Excel paste."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QHeaderView

from cueplayer.domain.models import Project, SetlistCategory, Song
from cueplayer.persistence.project_store import load_project, save_project
from cueplayer.ui.setlist_sheet_page import (
    build_setlist_sheet_rows,
    build_sheet_patch_lookup,
    folder_row_label,
    format_sheet_bpm,
    format_sheet_order,
    sheet_rows_to_tsv,
)


def test_format_sheet_order_zero_pads_integers() -> None:
    assert format_sheet_order(1) == "01"
    assert format_sheet_order(8.0) == "08"
    assert format_sheet_order(0.5) == "0.5"
    assert format_sheet_order(100) == "100"


def test_format_sheet_bpm() -> None:
    assert format_sheet_bpm(None) == ""
    assert format_sheet_bpm(87.0) == "87"
    assert format_sheet_bpm(87.5) == "87.5"


def test_build_setlist_sheet_rows_includes_folder_note_and_cue_id() -> None:
    project = Project.create("Jam")
    project.songs.clear()
    folder = SetlistCategory.create("Encore")
    project.setlist_categories.append(folder)
    a = Song.create("在這裡停一下")
    a.setlist_number = 1
    a.ma_export_name = "Stay a While"
    a.start_timecode = "01:00:00:00"
    a.bpm = 87
    a.note = "open soft"
    b = Song.create("乏善可陳")
    b.setlist_number = 8
    b.ma_export_name = "Fa Shan Ke Chen"
    b.start_timecode = "01:42:00:00"
    b.bpm = 104
    b.category_id = folder.id
    c = Song.create("海浪")
    c.setlist_number = 3
    c.ma_export_name = "Wave"
    c.start_timecode = "01:10:00:00"
    project.songs.extend([a, b, c])

    rows = build_setlist_sheet_rows(project)
    assert [r.kind for r in rows] == ["song", "song", "folder", "song"]
    assert rows[0].seq == "1"
    assert rows[0].cue_id == "Stay_a_While_Main"
    assert rows[1].seq == "2"
    assert rows[1].cue_id == "Wave_Main"
    assert rows[3].seq == "3"
    assert rows[3].cue_id == "Fa_Shan_Ke_Chen_Main"


def test_sheet_patch_follows_setlist_display_order() -> None:
    project = Project.create("Order")
    project.songs.clear()
    folder = SetlistCategory.create("B")
    project.setlist_categories.append(folder)
    main = Song.create("Main Song")
    main.ma_export_name = "MainSong"
    folder_song = Song.create("Folder Song")
    folder_song.ma_export_name = "FolderSong"
    folder_song.category_id = folder.id
    project.songs.extend([main, folder_song])
    patch = build_sheet_patch_lookup(project)
    assert patch[main.id].main_sequence == 1
    assert patch[folder_song.id].main_sequence == 2


def test_song_note_persists(tmp_path) -> None:
    project = Project.create("Notes")
    project.songs[0].note = "VIP 安可"
    path = tmp_path / "中文" / "notes.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.songs[0].note == "VIP 安可"


def test_build_setlist_sheet_rows_hides_collapsed_folder_songs() -> None:
    project = Project.create("Collapse")
    project.songs.clear()
    folder = SetlistCategory.create("Encore")
    folder.sheet_collapsed = True
    project.setlist_categories.append(folder)
    song = Song.create("Hidden")
    song.category_id = folder.id
    project.songs.append(song)
    rows = build_setlist_sheet_rows(project)
    assert len(rows) == 1
    assert rows[0].is_folder
    assert rows[0].collapsed is True
    folder.sheet_collapsed = False
    rows = build_setlist_sheet_rows(project)
    assert len(rows) == 2
    assert rows[1].name == "Hidden"


def test_sheet_and_setlist_folder_collapse_are_independent() -> None:
    project = Project.create("Independent")
    project.songs.clear()
    folder = SetlistCategory.create("VIP")
    folder.collapsed = True
    folder.sheet_collapsed = False
    project.setlist_categories.append(folder)
    song = Song.create("Inside")
    song.category_id = folder.id
    project.songs.append(song)
    rows = build_setlist_sheet_rows(project)
    assert len(rows) == 2
    assert rows[1].name == "Inside"
    folder.sheet_collapsed = True
    rows = build_setlist_sheet_rows(project)
    assert len(rows) == 1


def test_sheet_collapsed_persists(tmp_path) -> None:
    project = Project.create("Persist")
    folder = SetlistCategory.create("Fold")
    folder.sheet_collapsed = True
    project.setlist_categories = [folder]
    path = tmp_path / "sheet.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.setlist_categories[0].sheet_collapsed is True
    assert loaded.setlist_categories[0].collapsed is False


def test_folder_row_label_arrow() -> None:
    assert folder_row_label("VIP", collapsed=True) == "▸ VIP"
    assert folder_row_label("VIP", collapsed=False) == "▾ VIP"


def test_sheet_rows_to_tsv_includes_seq_cue_id_note() -> None:
    project = Project.create("Copy")
    folder = SetlistCategory.create("VIP")
    project.setlist_categories.append(folder)
    song = project.songs[0]
    song.name = "浴室"
    song.setlist_number = 5
    song.ma_export_name = "Bathroom"
    song.start_timecode = "01:20:00:00"
    song.bpm = 62
    song.note = "slow fade"
    song.category_id = folder.id
    text = sheet_rows_to_tsv(build_setlist_sheet_rows(project))
    lines = text.strip().split("\n")
    assert "Seq\tCue ID" in lines[0]
    assert lines[1] == "\t▾ VIP\t\t\t\t\t\t"
    assert "05\t浴室\tBathroom\t1\tBathroom_Main\t01:20:00:00\t62\tslow fade" in lines[2]


def test_set_list_sheet_ui_columns() -> None:
    from PySide6.QtWidgets import QApplication

    from cueplayer.ui.main_window import MainWindow, SetlistWidget

    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project.create("Sheet View"))
    assert window.toolbar.setlist_mode_button.text() == "Set List Sheet"

    header = window.song_list.horizontalHeader()
    assert header.sectionResizeMode(SetlistWidget.COL_NUM) == QHeaderView.ResizeMode.Fixed
    assert header.sectionResizeMode(SetlistWidget.COL_TITLE) == QHeaderView.ResizeMode.Interactive
    assert window.song_list.horizontalHeaderItem(SetlistWidget.COL_NUM).text() == "No."

    song = window.project.songs[0]
    song.name = "假設"
    song.ma_export_name = "If Only"
    song.start_timecode = "01:15:00:00"
    song.setlist_number = 4
    song.bpm = 76
    song.note = "check mic"
    window._rebuild_song_list(select_indexes=[0])

    window.toolbar.set_view_mode("setlist")
    window._set_view_mode("setlist")
    page = window.setlist_sheet_page
    assert page.table.columnCount() == 8
    assert page.table.horizontalHeaderItem(4).text() == "Cue ID"
    assert page.table.item(0, 3).text() == "1"
    assert page.table.item(0, 4).text() == "If_Only_Main"
    assert page.table.item(0, 7).text() == "check mic"

    page.copy_all()
    clip = app.clipboard().text()
    assert "If_Only_Main" in clip
    assert "check mic" in clip
