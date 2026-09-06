"""Main window title, Help > About menu, and About dialog use the canonical version."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.app_info import APP_NAME, APP_TITLE, APP_VERSION, COPYRIGHT
from cueplayer.domain.models import Project
from cueplayer.ui.about_dialog import AboutDialog
from cueplayer.ui.main_window import MAIN_WINDOW_TITLE_PREFIX, MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_main_window_title_prefix_is_canonical_app_title() -> None:
    assert MAIN_WINDOW_TITLE_PREFIX == APP_TITLE == "Cue Player 1.14"


def test_main_window_title_starts_with_app_title(app: QApplication) -> None:
    window = MainWindow(Project.create("TitleCheck"))
    window.show()
    app.processEvents()
    assert window.windowTitle().startswith(APP_TITLE)


def test_help_menu_has_about_action_at_far_right(app: QApplication) -> None:
    window = MainWindow(Project.create("MenuCheck"))
    menubar = window.menuBar()
    actions = [a for a in menubar.actions() if a.menu() is not None]
    assert actions, "menu bar should have top-level menus"
    last_menu = actions[-1].menu()
    assert last_menu is not None
    assert last_menu.title().replace("&", "") == "Help"
    about_titles = [a.text().replace("&", "") for a in last_menu.actions()]
    assert any("About" in t for t in about_titles)


def test_about_dialog_shows_canonical_version_and_copyright(app: QApplication) -> None:
    from PySide6.QtWidgets import QLabel

    dialog = AboutDialog()

    texts = [w.text() for w in dialog.findChildren(QLabel)]
    assert any(APP_NAME == t for t in texts)
    assert any(f"Version {APP_VERSION}" == t for t in texts)
    assert any(COPYRIGHT == t for t in texts)
