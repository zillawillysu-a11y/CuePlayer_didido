"""Embedded Video Preview right-click: Fit/Fill + decode quality."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow
from cueplayer.ui.video_preview import VideoPreviewWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_preview_widget_context_menu_emits_decode_quality(app: QApplication, monkeypatch) -> None:
    widget = VideoPreviewWidget(context_menu=True)
    widget.set_decode_quality("1080p")
    seen: list[str] = []
    widget.decode_quality_changed.connect(seen.append)

    from PySide6.QtWidgets import QMenu

    class _FakeMenu:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            del args, kwargs
            self._actions: list = []
            self._submenus: list = []

        def addAction(self, text):  # noqa: ANN001, N802
            from PySide6.QtGui import QAction

            action = QAction(text)
            action.setCheckable(True)
            self._actions.append(action)
            return action

        def addMenu(self, text):  # noqa: ANN001, N802
            del text
            sub = _FakeMenu()
            self._submenus.append(sub)
            return sub

        def addSeparator(self) -> None:
            return None

        def exec(self, _pos):  # noqa: ANN001
            # Pick "720p" from the quality submenu.
            quality_menu = self._submenus[0]
            for action in quality_menu._actions:
                if action.text() == "720p":
                    return action
            return None

    monkeypatch.setattr(
        "cueplayer.ui.video_preview.QMenu",
        _FakeMenu,
    )
    widget._show_context_menu(QPoint(10, 10))
    assert seen == ["720p"]
    assert widget.current_decode_quality() == "720p"


def test_main_window_preview_has_context_menu_and_wires_quality(
    app: QApplication,
) -> None:
    window = MainWindow(project=Project.create("預覽選單"))
    assert window.video_preview.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    window._set_video_decode_quality("540p")
    assert window.video_preview.current_decode_quality() == "540p"
    assert window.video_sync.decode_quality() == "540p"
