"""Digit mark shortcuts must not auto-repeat while a key is held."""

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


def test_digit_mark_shortcuts_disable_auto_repeat(app: QApplication) -> None:
    window = MainWindow()
    window.show()
    app.processEvents()

    assert len(window._digit_shortcuts) == 9
    assert all(not sc.autoRepeat() for sc in window._digit_shortcuts)


def test_digit_mark_shortcut_latch_blocks_repeat_activation(app: QApplication) -> None:
    window = MainWindow()
    window.show()
    app.processEvents()

    before = len(window.current_song.marks)
    window._add_mark_by_shortcut("1")
    after_first = len(window.current_song.marks)
    window._add_mark_by_shortcut("1")
    after_second = len(window.current_song.marks)

    assert after_first == before + 1
    assert after_second == after_first

    release = QKeyEvent(
        QEvent.Type.KeyRelease,
        Qt.Key.Key_1,
        Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(window, release)
    app.processEvents()

    window._add_mark_by_shortcut("1")
    assert len(window.current_song.marks) == after_first + 1
