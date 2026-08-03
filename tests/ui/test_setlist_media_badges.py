"""Setlist media column: Video (V) + LTC badges and column toggles."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioTrack, Project, VideoClip
from cueplayer.ui.main_window import MainWindow, SetlistWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _media_item(window: MainWindow, song_index: int = 0):
    for row in range(window.song_list.rowCount()):
        if window.song_list.row_song_index(row) == song_index:
            return window.song_list.item(row, SetlistWidget.COL_LTC)
    return None


def test_video_badge_role_when_song_has_clips(app: QApplication) -> None:
    window = MainWindow(Project.create("Video Badge"))
    song = window.project.songs[0]
    song.video_clips = [
        VideoClip.create("clip", Path("/fake/clip.mp4"), start_seconds=0.0)
    ]
    window._rebuild_song_list(select_indexes=[0])

    item = _media_item(window, 0)
    assert item is not None
    assert item.data(SetlistWidget.ROLE_HAS_VIDEO) is True


def test_media_column_hides_when_both_badges_off(app: QApplication) -> None:
    widget = SetlistWidget()
    widget.set_show_media_badges(show_ltc=False, show_video=False)
    assert widget.isColumnHidden(SetlistWidget.COL_LTC)
    widget.set_show_media_badges(show_ltc=True, show_video=False)
    assert not widget.isColumnHidden(SetlistWidget.COL_LTC)


def test_ltc_badge_still_populated(app: QApplication) -> None:
    window = MainWindow(Project.create("LTC"))
    song = window.project.songs[0]
    fake = Path(__file__).resolve()
    song.audio_tracks = [
        AudioTrack(id="main", name="t", path=fake, role="main")
    ]
    key = window._audio_cache_key(fake)
    assert key is not None
    window._audio_ltc_cache[key] = 1
    window._rebuild_song_list(select_indexes=[0])
    item = _media_item(window, 0)
    assert item is not None
    assert item.data(SetlistWidget.ROLE_LTC_CHANNEL) == 1
