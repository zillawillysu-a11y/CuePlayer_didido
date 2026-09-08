"""Ctrl-click keeps multiple timeline Marks selected."""

from __future__ import annotations

import os

import pytest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project, Song
from cueplayer.ui.main_window import MainWindow
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_ctrl_click_adds_second_mark_to_selection(app: QApplication) -> None:
    timeline = TimelineWidget()
    song = Song.create("Multi")
    first = song.add_mark(1, 1.0)
    second = song.add_mark(1, 2.0)
    timeline.set_song(song)
    timeline.resize(1000, 600)
    timeline.show()
    app.processEvents()
    lane = next(rect for rect in timeline._lane_rects() if rect[0] == 1)
    y = int((lane[1] + lane[2]) / 2)

    QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=QPoint(int(timeline._x_for_time(1.0)), y))
    QTest.keyPress(timeline, Qt.Key.Key_Control)
    QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=QPoint(int(timeline._x_for_time(2.0)), y))
    QTest.keyRelease(timeline, Qt.Key.Key_Control)

    assert set(timeline.selected_mark_ids()) == {first.id, second.id}


def test_native_ctrl_state_adds_to_selection_without_qt_modifier(app: QApplication) -> None:
    timeline = TimelineWidget()
    song = Song.create("Native Ctrl")
    first = song.add_mark(1, 1.0)
    second = song.add_mark(1, 2.0)
    timeline.set_song(song)
    timeline.resize(1000, 600)
    timeline.show()
    app.processEvents()
    lane = next(rect for rect in timeline._lane_rects() if rect[0] == 1)
    y = int((lane[1] + lane[2]) / 2)
    QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=QPoint(int(timeline._x_for_time(1.0)), y))

    with patch("cueplayer.ui.timeline_widget._native_control_key_down", return_value=True):
        QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=QPoint(int(timeline._x_for_time(2.0)), y))

    assert set(timeline.selected_mark_ids()) == {first.id, second.id}


def test_main_window_tracks_ctrl_even_when_key_event_targets_window(app: QApplication) -> None:
    window = MainWindow(Project.create("Global Ctrl"))
    timeline = window.timeline
    first = window.current_song.add_mark(1, 1.0)
    second = window.current_song.add_mark(1, 2.0)
    timeline.set_song(window.current_song)
    window.monitor.set_song(window.current_song)
    window.monitor.refresh_list()
    timeline.resize(1000, 600)
    timeline.show()
    window.show()
    app.processEvents()
    lane = next(rect for rect in timeline._lane_rects() if rect[0] == 1)
    y = int((lane[1] + lane[2]) / 2)

    QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=QPoint(int(timeline._x_for_time(1.0)), y))
    QTest.keyPress(window, Qt.Key.Key_Control)
    QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=QPoint(int(timeline._x_for_time(2.0)), y))
    QTest.keyRelease(window, Qt.Key.Key_Control)
    app.processEvents()

    assert set(timeline.selected_mark_ids()) == {first.id, second.id}
