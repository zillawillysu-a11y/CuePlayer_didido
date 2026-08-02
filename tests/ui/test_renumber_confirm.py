"""Cue List and Set List renumber require a Yes/No confirmation."""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_cue_list_renumber_cancelled_keeps_ids(app: QApplication) -> None:
    project = Project.create("CueConfirm")
    song = project.songs[0]
    a = song.add_mark(1, 1.0)
    b = song.add_mark(1, 2.0)
    a.main_cue_id = "10"
    b.main_cue_id = "20"
    window = MainWindow(project)
    with patch.object(
        QMessageBox,
        "question",
        return_value=QMessageBox.StandardButton.No,
    ) as ask:
        window._renumber_main_cue_ids(None)
    ask.assert_called_once()
    assert a.main_cue_id == "10"
    assert b.main_cue_id == "20"


def test_cue_list_renumber_yes_rewrites_ids(app: QApplication) -> None:
    project = Project.create("CueYes")
    song = project.songs[0]
    a = song.add_mark(1, 1.0)
    b = song.add_mark(1, 2.0)
    a.main_cue_id = "10"
    b.main_cue_id = "20"
    window = MainWindow(project)
    with patch.object(
        QMessageBox,
        "question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        window._renumber_main_cue_ids(None)
    assert a.main_cue_id == "1"
    assert b.main_cue_id == "2"


def test_setlist_renumber_cancelled_keeps_numbers(app: QApplication) -> None:
    project = Project.create("SetConfirm")
    a = project.songs[0]
    a.setlist_number = 5.0
    b = project.new_song("Second")
    b.setlist_number = 9.0
    project.songs.append(b)
    with patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True):
        window = MainWindow(project=project)
        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.No,
        ) as ask:
            window._renumber_songs_in_category(None)
        ask.assert_called_once()
        assert [s.setlist_number for s in project.songs] == [5.0, 9.0]
