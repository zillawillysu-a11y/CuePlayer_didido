"""New Folder with selected songs; Add Song into a folder."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QInputDialog

from cueplayer.domain.models import Project, SetlistCategory
from cueplayer.ui.main_window import MainWindow
from cueplayer.ui.song_edit_dialog import SongDraft, SongEditDialog


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_new_folder_wraps_selected_songs(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = Project.create("Wrap")
    s1 = project.songs[0]
    s1.name = "One"
    s2 = project.new_song("Two")
    project.songs.append(s2)
    window = MainWindow(project)
    window.show()
    app.processEvents()

    # Select both songs in the setlist model indexes.
    window.song_list.selectAll()
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("Today", True)
    )
    window._add_setlist_category(wrap_selected=True)

    assert len(project.setlist_categories) == 1
    folder = project.setlist_categories[0]
    assert folder.name == "Today"
    assert s1.category_id == folder.id
    assert s2.category_id == folder.id


def test_add_song_into_folder(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = Project.create("AddIn")
    folder = SetlistCategory.create("Show")
    project.setlist_categories = [folder]
    window = MainWindow(project)
    window.show()
    app.processEvents()

    draft = SongDraft(name="Inside", setlist_number=1.0)

    class _FakeDialog:
        def __init__(self, *a, **k):  # noqa: ANN002, ANN003
            pass

        def exec(self) -> int:
            return 1

        def result_drafts(self):
            return [draft]

    monkeypatch.setattr(
        "cueplayer.ui.main_window.SongEditDialog", _FakeDialog
    )
    before = len(project.songs)
    window._add_song(folder.id)
    assert len(project.songs) == before + 1
    assert project.songs[-1].category_id == folder.id
    assert project.songs[-1].name == "Inside"
