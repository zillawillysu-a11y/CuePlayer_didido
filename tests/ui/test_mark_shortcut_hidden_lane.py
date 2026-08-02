"""Digit shortcuts must not add marks on hidden Mark tracks."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _release_digit(app: QApplication, window: MainWindow, digit: int) -> None:
    key = getattr(Qt.Key, f"Key_{digit}")
    release = QKeyEvent(QEvent.Type.KeyRelease, key, Qt.KeyboardModifier.NoModifier)
    app.sendEvent(window, release)
    app.processEvents()


def test_hidden_lane_shortcut_does_not_add_mark(app: QApplication) -> None:
    window = MainWindow()
    window.show()
    app.processEvents()
    song = window.current_song

    lane4 = song.lane_by_shortcut("4")
    assert lane4 is not None
    lane4.visible = False

    before = len(song.marks)
    window._add_mark_by_shortcut("4")
    assert len(song.marks) == before

    _release_digit(app, window, 4)
    # Visible lane still works.
    window._add_mark_by_shortcut("1")
    assert len(song.marks) == before + 1


def test_add_mark_ignores_hidden_lane_index(app: QApplication) -> None:
    window = MainWindow()
    window.show()
    app.processEvents()
    song = window.current_song

    lane5 = song.lane_by_index(5)
    assert lane5 is not None
    lane5.visible = False
    before = len(song.marks)
    window._add_mark(5)
    assert len(song.marks) == before
