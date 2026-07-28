"""Setlist sheet rows + TSV for MA3 / Excel paste."""

from __future__ import annotations

import os

import pytest

# Headless CI / cloud agents: Qt needs an offscreen platform.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QHeaderView

from cueplayer.domain.models import Project, SetlistCategory, Song
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


def test_build_setlist_sheet_rows_includes_folder_separators() -> None:
    project = Project.create("Jam")
    project.songs.clear()
    folder = SetlistCategory.create("Encore")
    project.setlist_categories.append(folder)
    a = Song.create("在這裡停一下")
    a.setlist_number = 1
    a.ma_export_name = "Stay a While"
    a.start_timecode = "01:00:00:00"
    a.bpm = 87
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
    assert rows[0].order == "01"
    assert rows[0].english_name == "Stay a While"
    assert rows[2].is_folder is True
    assert rows[3].order == "08"


def test_sheet_rows_to_tsv_includes_folder_lines() -> None:
    project = Project.create("Copy")
    folder = SetlistCategory.create("VIP")
    project.setlist_categories.append(folder)
    song = project.songs[0]
    song.name = "浴室"
    song.setlist_number = 5
    song.ma_export_name = "Bathroom"
    song.start_timecode = "01:20:00:00"
    song.bpm = 62
    song.category_id = folder.id
    text = sheet_rows_to_tsv(build_setlist_sheet_rows(project))
    lines = text.strip().split("\n")
    assert lines[0].startswith("曲序\t曲名\t英文名\tTimecode Generator\tBPM")
    assert lines[1] == "\t▸ VIP\t\t\t"
    assert "05\t浴室\tBathroom\t01:20:00:00\t62" in lines[2]


def test_setlist_sheet_page_folders_and_resizable_columns() -> None:
    from PySide6.QtWidgets import QApplication

    from cueplayer.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow(Project.create("Sheet View"))
    folder = SetlistCategory.create("安可")
    window.project.setlist_categories.append(folder)
    song = window.project.songs[0]
    song.name = "假設"
    song.ma_export_name = "If Only"
    song.start_timecode = "01:15:00:00"
    song.setlist_number = 4
    song.bpm = 76
    song.category_id = folder.id
    window._rebuild_song_list(select_indexes=[0])

    window.toolbar.set_view_mode("setlist")
    window._set_view_mode("setlist")
    page = window.setlist_sheet_page
    assert window.view_stack.currentIndex() == 2
    assert page.table.rowCount() == 2
    assert page.table.item(0, 0).text() == "▸ 安可"
    assert page.table.columnSpan(0, 0) == 5
    assert page.table.item(1, 0).text() == "04"
    assert page.table.item(1, 1).text() == "假設"

    header = page.table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Interactive
    assert header.sectionResizeMode(1) == QHeaderView.ResizeMode.Interactive
    header.resizeSection(1, 300)
    assert header.sectionSize(1) == 300

    page.copy_all()
    clip = app.clipboard().text()
    assert "▸ 安可" in clip
    assert "If Only" in clip
    assert "01:15:00:00" in clip
