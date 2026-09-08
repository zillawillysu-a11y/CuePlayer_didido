"""Inline Note/Cue ID commits must not rebuild and destroy the next editor."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_note_commit_refreshes_timeline_without_rebuilding_cue_list(
    app: QApplication,
) -> None:
    project = Project.create("No Note rebuild")
    mark = project.songs[0].add_mark(1, 1.0)
    window = MainWindow(project=project)

    with patch.object(window, "_schedule_cue_list_refresh") as schedule:
        window._on_note_changed(mark.id, "", "New Note")

    schedule.assert_not_called()


def test_cue_id_commit_refreshes_timeline_without_rebuilding_cue_list(
    app: QApplication,
) -> None:
    project = Project.create("No Cue ID rebuild")
    mark = project.songs[0].add_mark(1, 1.0)
    window = MainWindow(project=project)

    with patch.object(window, "_schedule_cue_list_refresh") as schedule:
        window._on_cue_id_changed(mark.id, "1", "2")

    schedule.assert_not_called()
