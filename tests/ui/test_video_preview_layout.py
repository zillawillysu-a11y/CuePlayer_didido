"""Main window layout: Video Preview under Mark Timeline, not under Cue list."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QSplitter

from cueplayer.domain.models import Project
from cueplayer.ui import main_window as mw
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_video_preview_is_under_timeline_not_cuelist(app: QApplication) -> None:
    window = MainWindow(project=Project.create("版面測試"))
    preview = window.video_preview_panel
    monitor = window.monitor
    timeline = window.timeline

    preview_split = preview.parentWidget()
    assert isinstance(preview_split, QSplitter)
    assert preview_split.objectName() == "timelinePreviewSplitter"
    assert window._timeline_scroll.widget() is timeline
    assert preview_split.indexOf(window._timeline_center) == 0
    assert preview_split.indexOf(preview) == 1

    # Cue list must not contain the preview.
    assert not monitor.isAncestorOf(preview)
    assert preview.parentWidget() is not monitor

    horiz = preview_split.parentWidget()
    assert isinstance(horiz, QSplitter)
    assert horiz.objectName() == "timelineSplit"
    assert horiz.indexOf(preview_split) == 0
    assert horiz.indexOf(monitor) == 1


def test_video_preview_splitter_cannot_drag_collapse(app: QApplication) -> None:
    window = MainWindow(project=Project.create("Preview Floor"))
    split = window._timeline_preview_split
    assert split is not None
    assert split.isCollapsible(1) is False
    assert window.video_preview_panel.minimumHeight() >= mw._VIDEO_PREVIEW_SPLIT_MIN_HEIGHT

    # Simulate a previous session that saved Preview height as 0.
    total = max(400, split.height())
    split.setSizes([total, 0])
    window._clamp_video_preview_splitter()
    sizes = split.sizes()
    assert sizes[1] >= mw._VIDEO_PREVIEW_SPLIT_MIN_HEIGHT


def test_video_preview_visibility_restores_from_machine_setting(
    app: QApplication,
) -> None:
    window = MainWindow(project=Project.create("Preview visibility"))
    settings = window._settings
    existed = settings.contains(mw._KEY_VIDEO_PREVIEW_VISIBLE)
    previous = settings.value(mw._KEY_VIDEO_PREVIEW_VISIBLE)
    settings.setValue(mw._KEY_VIDEO_PREVIEW_VISIBLE, False)

    try:
        window._restore_ui_layout()

        assert not window.video_preview_panel.isVisible()
        assert not window._act_video_preview.isChecked()
    finally:
        if existed:
            settings.setValue(mw._KEY_VIDEO_PREVIEW_VISIBLE, previous)
        else:
            settings.store.remove(mw._KEY_VIDEO_PREVIEW_VISIBLE)


def test_video_preview_toggle_persists_machine_setting(app: QApplication) -> None:
    window = MainWindow(project=Project.create("Preview toggle"))
    settings = window._settings
    existed = settings.contains(mw._KEY_VIDEO_PREVIEW_VISIBLE)
    previous = settings.value(mw._KEY_VIDEO_PREVIEW_VISIBLE)

    try:
        window._toggle_video_preview_panel(False)

        assert settings.value(mw._KEY_VIDEO_PREVIEW_VISIBLE, True, type=bool) is False
    finally:
        if existed:
            settings.setValue(mw._KEY_VIDEO_PREVIEW_VISIBLE, previous)
        else:
            settings.store.remove(mw._KEY_VIDEO_PREVIEW_VISIBLE)
