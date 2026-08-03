"""Delete mark undo survives song switches."""

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


def test_delete_mark_undo_after_song_switch(app: QApplication) -> None:
    project = Project.create("Undo Delete")
    second = project.new_song("Second")
    project.songs.append(second)
    mark = project.songs[0].add_mark(1, 1.0)

    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(project=project)
        window._delete_marks([mark.id])
        assert len(project.songs[0].marks) == 0

        window._activate_song(1)
        window._activate_song(0)

        window._undo_action()
        assert len(project.songs[0].marks) == 1
        window.close()
        app.processEvents()
