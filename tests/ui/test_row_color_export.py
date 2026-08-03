"""Export / Show Patch song lists carry Song.row_color for painted rows."""

from __future__ import annotations

import os

import pytest

# Headless CI / cloud agents: Qt needs an offscreen platform + EGL libs.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cueplayer.domain.models import Project  # noqa: E402
from cueplayer.ui.export_dialog import ExportDialog  # noqa: E402
from cueplayer.ui.row_color import ROLE_ROW_COLOR  # noqa: E402
from cueplayer.ui.show_patch_page import ShowPatchPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_export_dialog_stores_row_color_on_items(qapp: QApplication) -> None:
    project = Project.create("Show")
    project.songs[0].name = "VIP"
    project.songs[0].row_color = "#FF5A5F"
    project.songs.append(project.new_song("Normal"))
    dialog = ExportDialog(project.songs)
    assert dialog.song_list.count() == 2
    assert dialog.song_list.item(0).data(ROLE_ROW_COLOR) == "#FF5A5F"
    assert dialog.song_list.item(1).data(ROLE_ROW_COLOR) in ("", None)


def test_show_patch_song_pick_stores_row_color(qapp: QApplication) -> None:
    project = Project.create("Show")
    project.songs[0].name = "問題曲"
    project.songs[0].row_color = "#D29922"
    page = ShowPatchPage()
    page.set_project(project)
    assert page.song_pick.count() == 1
    assert page.song_pick.item(0).data(ROLE_ROW_COLOR) == "#D29922"
