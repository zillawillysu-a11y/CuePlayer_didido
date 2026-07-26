"""Verify MainWindow shutdown closes CleanVideoOutputWindow and quits the app."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(True)
    return instance


def _visible_titles(app: QApplication) -> list[str]:
    return [w.windowTitle() for w in app.topLevelWidgets() if w.isVisible()]


def test_main_close_quits_with_clean_output_open(app: QApplication) -> None:
    quit_calls = {"count": 0}
    original_quit = app.quit

    def tracked_quit() -> None:
        quit_calls["count"] += 1
        original_quit()

    app.quit = tracked_quit  # type: ignore[method-assign]

    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(project=Project.create("Test"))
        window.show()
        window.clean_output_window.show()
        assert "CuePlayer Clean Video Output" in _visible_titles(app)

        window.close()
        app.processEvents()

        assert _visible_titles(app) == []
        assert quit_calls["count"] == 1

    app.quit = original_quit  # type: ignore[method-assign]


def test_main_close_quits_with_clean_output_fullscreen(app: QApplication) -> None:
    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(project=Project.create("Test"))
        window.show()
        window.clean_output_window.showFullScreen()

        window.close()
        app.processEvents()

        assert _visible_titles(app) == []
