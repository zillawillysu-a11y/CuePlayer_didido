"""Setlist footer buttons must not clip labels when the panel is narrow."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_setlist_footer_compacts_when_narrow(app: QApplication) -> None:
    window = MainWindow(Project.create("Compact"))
    window.show()
    app.processEvents()
    panel = window._setlist_panel
    main = window._main_splitter
    total = sum(main.sizes())
    main.setSizes([160, max(280, total - 160)])
    app.processEvents()
    window._fit_setlist_footer()
    app.processEvents()

    assert window._setlist_footer_compact is True
    assert window.delete_song_button.text() == "Del"
    assert window.sort_by_number_button.text() == "Sort #"
    assert window.renumber_button.text() == "Re#"
    # Buttons stay fully inside the panel (no horizontal overflow clip).
    footer = window._setlist_footer
    assert footer.width() <= panel.width()
    for button in (
        window.add_song_button,
        window.edit_song_button,
        window.delete_song_button,
        window.sort_by_number_button,
        window.renumber_button,
    ):
        assert button.width() > 0
        right = button.mapTo(panel, button.rect().topRight()).x()
        left = button.mapTo(panel, button.rect().topLeft()).x()
        assert left >= -1
        assert right <= panel.width() + 1


def test_setlist_footer_full_labels_when_wide(app: QApplication) -> None:
    window = MainWindow(Project.create("Wide"))
    window.show()
    window.setGeometry(0, 0, 1600, 900)
    app.processEvents()
    window._pending_restore_geometry = None
    window.setGeometry(0, 0, 1600, 900)
    app.processEvents()
    window._main_splitter.setSizes([320, 1280])
    app.processEvents()
    window._fit_setlist_footer()
    app.processEvents()

    assert window._setlist_footer_compact is False
    assert window.delete_song_button.text() == "Delete"
    assert window.sort_by_number_button.text() == "Sort by Number"
    assert window.renumber_button.text() == "Renumber"
