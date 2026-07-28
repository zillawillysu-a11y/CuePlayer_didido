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


def test_build_setlist_sheet_rows_includes_folder_and_note() -> None:
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
    assert [r.name for r in rows] == ["在這裡停一下", "海浪", "Encore", "乏善可陳"]
    assert rows[0].note == "open soft"
    assert rows[2].is_folder is True


def test_song_note_persists(tmp_path) -> None:
    project = Project.create("Notes")
    project.songs[0].note = "VIP 安可"
    path = tmp_path / "中文" / "notes.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.songs[0].note == "VIP 安可"


def test_sheet_rows_to_tsv_includes_note_and_folder() -> None:
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
    assert lines[0].startswith("曲序\t曲名\t英文名\tTimecode Generator\tBPM\tNote")
    assert lines[1] == "\t▸ VIP\t\t\t\t"
    assert "05\t浴室\tBathroom\t01:20:00:00\t62\tslow fade" in lines[2]


def test_set_list_sheet_button_label_and_editable_order() -> None:
    from PySide6.QtWidgets import QApplication

    from cueplayer.ui.main_window import MainWindow, SetlistWidget

    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project.create("Sheet View"))
    assert window.toolbar.setlist_mode_button.text() == "Set List Sheet"

    header = window.song_list.horizontalHeader()
    assert header.sectionResizeMode(SetlistWidget.COL_NUM) == QHeaderView.ResizeMode.Interactive
    assert header.sectionResizeMode(SetlistWidget.COL_BPM) == QHeaderView.ResizeMode.Interactive

    folder = SetlistCategory.create("安可")
    window.project.setlist_categories.append(folder)
    song = window.project.songs[0]
    song.name = "假設"
    song.ma_export_name = "If Only"
    song.start_timecode = "01:15:00:00"
    song.setlist_number = 4
    song.bpm = 76
    song.note = "check mic"
    song.category_id = folder.id
    window._rebuild_song_list(select_indexes=[0])

    window.toolbar.set_view_mode("setlist")
    window._set_view_mode("setlist")
    page = window.setlist_sheet_page
    assert page.table.columnCount() == 6
    assert page.table.horizontalHeaderItem(5).text() == "Note"
    assert page.table.item(0, 0).text() == "▸ 安可"
    assert page.table.item(1, 0).text() == "04"
    assert page.table.item(1, 5).text() == "check mic"
    # 曲序 is editable
    flags = page.table.item(1, 0).flags()
    from PySide6.QtCore import Qt

    assert flags & Qt.ItemFlag.ItemIsEditable

    page.copy_all()
    clip = app.clipboard().text()
    assert "▸ 安可" in clip
    assert "check mic" in clip
    assert "If Only" in clip
