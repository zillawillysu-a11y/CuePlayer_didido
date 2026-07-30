"""Auto-Save interval can be chosen in minutes from the File menu."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import (
    MainWindow,
    _AUTOSAVE_INTERVAL_MINUTES,
    _KEY_AUTOSAVE_ENABLED,
    _KEY_AUTOSAVE_INTERVAL_SEC,
)


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_autosave_menu_offers_minute_choices(app: QApplication) -> None:
    window = MainWindow(Project.create("AutoSave"))
    assert hasattr(window, "_autosave_off_action")
    assert set(window._autosave_interval_actions) == set(_AUTOSAVE_INTERVAL_MINUTES)


def test_set_autosave_choice_minutes_enables_timer(app: QApplication) -> None:
    window = MainWindow(Project.create("AutoSave"))
    window._set_autosave_choice(5)
    assert window._autosave_enabled() is True
    assert window._autosave_interval_seconds() == 300
    assert window._autosave_interval_minutes() == 5
    assert window._settings.value(_KEY_AUTOSAVE_INTERVAL_SEC, type=int) == 300
    assert window._autosave_timer.isActive()
    assert window._autosave_interval_actions[5].isChecked()


def test_set_autosave_choice_off_stops_timer(app: QApplication) -> None:
    window = MainWindow(Project.create("AutoSave"))
    window._set_autosave_choice(2)
    window._set_autosave_choice(None)
    assert window._autosave_enabled() is False
    assert window._settings.value(_KEY_AUTOSAVE_ENABLED, type=bool) is False
    assert not window._autosave_timer.isActive()
    assert window._autosave_off_action.isChecked()
