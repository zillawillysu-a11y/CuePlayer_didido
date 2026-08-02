"""Clean Video Output visibility restores from saved project settings."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import CleanVideoOutputSettings, Project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_clean_output_restores_when_project_was_open(app: QApplication) -> None:
    project = Project.create("Restore Test")
    project.clean_video_output = CleanVideoOutputSettings(was_open=True)

    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(project=project)
        window.show()
        app.processEvents()

        assert window.clean_output_window.isVisible()
        assert window._clean_output_action.isChecked()
        window.close()
        app.processEvents()


def test_clean_output_stays_hidden_when_project_was_closed(app: QApplication) -> None:
    project = Project.create("Hidden Test")
    project.clean_video_output = CleanVideoOutputSettings(was_open=False)

    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(project=project)
        window.show()
        app.processEvents()

        assert not window.clean_output_window.isVisible()
        assert not window._clean_output_action.isChecked()
        window.close()
        app.processEvents()
