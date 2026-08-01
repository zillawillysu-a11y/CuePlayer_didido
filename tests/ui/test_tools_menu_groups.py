"""Tools keeps BPM/Video; View holds preview / track / clean output toggles."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _menu_titles(window: MainWindow, path: list[str]) -> list[str]:
    menu = window.menuBar()
    for title in path:
        want = title.replace("&", "")
        found = None
        for action in menu.actions():
            if action.isSeparator():
                continue
            if action.text().replace("&", "") == want:
                found = action.menu()
                break
        assert found is not None, f"menu {title!r} not found under {path}"
        menu = found
    return [
        a.text().replace("&", "")
        for a in menu.actions()
        if not a.isSeparator()
    ]


def _top_level_titles(window: MainWindow) -> list[str]:
    return [
        a.text().replace("&", "")
        for a in window.menuBar().actions()
        if a.menu() is not None
    ]


def test_tools_bpm_and_video_are_submenus(app: QApplication) -> None:
    window = MainWindow(Project.create("Tools"))
    top_titles = _menu_titles(window, ["Tools"])
    assert "BPM" in top_titles
    assert "Video" in top_titles
    assert "Show Video / LTC Tracks" not in top_titles
    assert "Detect BPM (songs without BPM)" not in top_titles
    assert "Add Video Clip…" not in top_titles
    assert "Clean Video Output" not in top_titles
    assert "Video Preview Panel" not in top_titles

    bpm_titles = _menu_titles(window, ["Tools", "BPM"])
    assert "Detect BPM (songs without BPM)" in bpm_titles
    assert "Re-detect BPM (auto / empty only)" in bpm_titles

    video_titles = _menu_titles(window, ["Tools", "Video"])
    assert "Add Video Clip…" in video_titles
    assert "Video Preview Panel" not in video_titles
    assert "Clean Video Output" not in video_titles
    assert "NDI Video Output" in video_titles
    assert "NDI Source Name…" in video_titles
    assert "Video Decode Quality" in video_titles


def test_view_menu_holds_preview_track_clean(app: QApplication) -> None:
    window = MainWindow(Project.create("View"))
    assert _top_level_titles(window) == ["File", "Tools", "View"]

    view_titles = _menu_titles(window, ["View"])
    assert view_titles == [
        "Show Video / LTC Tracks",
        "Video Preview Panel",
        "Clean Video Output",
    ]
