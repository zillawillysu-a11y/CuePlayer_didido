"""Feature flag + experimental Tools menu hide (Sprint 8 Task 1)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.features import ENABLE_EXPERIMENTAL_FEATURES
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_experimental_features_flag_default_off() -> None:
    assert ENABLE_EXPERIMENTAL_FEATURES is False


def test_tools_menu_hides_align_and_preflight(app: QApplication) -> None:
    window = MainWindow(Project.create("Hide"))
    tools = None
    for action in window.menuBar().actions():
        if action.text().replace("&", "") == "Tools":
            tools = action.menu()
            break
    assert tools is not None
    labels = [a.text().replace("&", "") for a in tools.actions() if not a.isSeparator()]
    assert "Align Anchors…" not in labels
    assert "MA Preflight…" not in labels
    # Production Tools entries remain.
    assert any("Audio" in t for t in labels)
    window.close()
