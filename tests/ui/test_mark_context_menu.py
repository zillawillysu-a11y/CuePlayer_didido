"""Waveform / timeline mark context menu: delete, rename note, change type."""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu

from cueplayer.domain.models import Project, Song
from cueplayer.domain.undo import ChangeMarkLanesCommand
from cueplayer.ui.main_window import MainWindow
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_mark_context_menu_actions_exist(app: QApplication) -> None:
    widget = TimelineWidget()
    song = Song.create("Menu")
    mark = song.add_mark(1, 1.0, display_name="OLD")
    widget.set_song(song)
    widget.set_selected_mark_ids([mark.id])
    widget.resize(900, 500)
    widget.show()
    app.processEvents()

    captured: dict[str, object] = {"type_titles": []}

    class FakeMenu(QMenu):
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            super().__init__(*args, **kwargs)

        def addMenu(self, *args, **kwargs):  # noqa: ANN002, ANN003, N802
            sub = super().addMenu(*args, **kwargs)
            # Capture while the submenu is still alive.
            captured["type_menu"] = sub
            return sub

        def exec(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            captured["titles"] = [a.text() for a in self.actions() if a.text()]
            sub = captured.get("type_menu")
            if isinstance(sub, QMenu):
                captured["type_titles"] = [a.text() for a in sub.actions()]
            return None

    with patch("cueplayer.ui.timeline_widget.QMenu", FakeMenu):
        widget._show_mark_item_context_menu(QPoint(200, 40), [mark.id])

    titles = captured["titles"]
    assert any(t.startswith("Delete Mark") for t in titles)
    assert "Rename Note…" in titles
    assert any("Change Type" in t for t in titles)
    assert "Offset Time…" in titles
    assert any("Main" in t for t in captured["type_titles"])


def test_rename_note_from_mark_menu(app: QApplication) -> None:
    window = MainWindow(Project.create("Rename"))
    song = window.current_song
    mark = song.add_mark(1, 1.0, display_name="OLD")
    window.timeline.set_song(song)
    window.timeline.set_selected_mark_ids([mark.id])
    app.processEvents()

    class FakeMenu(QMenu):
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            super().__init__(*args, **kwargs)
            self._rename = None

        def addAction(self, *args, **kwargs):  # noqa: ANN002, ANN003, N802
            act = super().addAction(*args, **kwargs)
            if act.text() == "Rename Note…":
                self._rename = act
            return act

        def exec(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self._rename

    with (
        patch("cueplayer.ui.timeline_widget.QMenu", FakeMenu),
        patch.object(QInputDialog, "getText", return_value=("NEW", True)),
    ):
        window.timeline._show_mark_item_context_menu(QPoint(10, 10), [mark.id])
    app.processEvents()
    assert mark.display_name == "NEW"


def test_change_mark_type_updates_lane_and_undo(app: QApplication) -> None:
    window = MainWindow(Project.create("Type"))
    song = window.current_song
    mark = song.add_mark(1, 1.0, display_name="X")
    assert mark.lane_index == 1
    target = next(lane.index for lane in song.mark_lanes if lane.index != 1)
    window._change_mark_types([mark.id], target)
    assert mark.lane_index == target
    # Undo restores lane.
    window._undo_action()
    assert mark.lane_index == 1


def test_change_mark_lanes_command_roundtrip() -> None:
    song = Song.create("Cmd")
    mark = song.add_mark(1, 1.0)
    old_lane = mark.lane_index
    new_lane = 2
    old_cue = mark.main_cue_id
    mark.lane_index = new_lane
    mark.main_cue_id = ""
    cmd = ChangeMarkLanesCommand(
        changes={mark.id: (old_lane, new_lane, old_cue, "")}
    )
    cmd.undo(song)
    assert mark.lane_index == old_lane
    assert mark.main_cue_id == old_cue
    cmd.redo(song)
    assert mark.lane_index == new_lane
    assert mark.main_cue_id == ""
