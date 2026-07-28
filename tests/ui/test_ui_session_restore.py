"""Main window layout and last-project session restore."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.persistence.project_store import save_project
from cueplayer.ui.main_window import (
    MainWindow,
    _KEY_LAST_PROJECT,
    _KEY_LAST_SONG_ID,
    _KEY_MAIN_GEOMETRY,
    _KEY_VIEW_MODE,
    _SETTINGS_APP,
    _SETTINGS_ORG,
)


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path: Path) -> QSettings:
    path = tmp_path / "session.ini"
    s = QSettings(str(path), QSettings.Format.IniFormat)
    s.clear()
    return s


def test_ui_session_saved_on_close(app: QApplication, settings: QSettings, tmp_path: Path) -> None:
    project_path = tmp_path / "show.cueplayer.json"
    save_project(Project.create("Session Test"), project_path)

    with (
        patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True),
        patch("cueplayer.ui.main_window.QSettings", return_value=settings),
    ):
        window = MainWindow()
        window.resize(1234, 567)
        window._project_path = project_path
        window.view_stack.setCurrentIndex(1)
        window.show()
        app.processEvents()
        song_id = window.current_song.id
        window.close()
        app.processEvents()

    assert settings.value(_KEY_MAIN_GEOMETRY) is not None
    assert settings.value(_KEY_VIEW_MODE) == "ma_patch"
    assert settings.value(_KEY_LAST_PROJECT) == str(project_path)
    assert settings.value(_KEY_LAST_SONG_ID) == song_id


def test_last_project_and_song_restore_on_startup(
    app: QApplication, settings: QSettings, tmp_path: Path
) -> None:
    project = Project.create("Restore")
    second = project.new_song("Second Song")
    project.songs.append(second)
    project_path = tmp_path / "restore.cueplayer.json"
    save_project(project, project_path)

    settings.setValue(_KEY_LAST_PROJECT, str(project_path))
    settings.setValue(_KEY_LAST_SONG_ID, second.id)

    with (
        patch.object(MainWindow, "_confirm_discard_if_dirty", return_value=True),
        patch("cueplayer.ui.main_window.QSettings", return_value=settings),
        patch.object(MainWindow, "_maybe_load_demo_fixture"),
    ):
        window = MainWindow()
        app.processEvents()

    assert window._project_path == project_path
    assert window.current_song.id == second.id


def test_settings_org_keys_are_stable() -> None:
    assert _SETTINGS_ORG == "CuePlayer"
    assert _SETTINGS_APP == "CuePlayer"
