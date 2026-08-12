"""Keyboard S toggles Mark movement mode and its overlay chip together."""

from __future__ import annotations

import os

import pytest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLineEdit

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _s_shortcut(window: MainWindow) -> QShortcut:
    return next(
        shortcut
        for shortcut in window.findChildren(QShortcut)
        if shortcut.key() == QKeySequence("S")
    )


def test_s_toggles_setup_mode_and_button_indicator(app: QApplication) -> None:
    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(Project.create("Setup shortcut"))
        shortcut = _s_shortcut(window)

        assert window.timeline.setup_mode_enabled() is False
        assert window.timeline.setup_button._active is False

        shortcut.activated.emit()
        assert window.timeline.setup_mode_enabled() is True
        assert window.timeline.setup_button._active is True

        shortcut.activated.emit()
        assert window.timeline.setup_mode_enabled() is False
        assert window.timeline.setup_button._active is False
        window.close()
        app.processEvents()


def test_s_is_not_consumed_while_typing(app: QApplication) -> None:
    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(Project.create("Typing shortcut"))
        editor = QLineEdit(window)
        editor.show()
        window.show()
        editor.setFocus()
        app.processEvents()

        _s_shortcut(window).activated.emit()

        assert window.timeline.setup_mode_enabled() is False
        assert window.timeline.setup_button._active is False
        window.close()
        app.processEvents()
