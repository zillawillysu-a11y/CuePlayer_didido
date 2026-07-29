"""Setlist striped-LTC badge (LTC + L/R) on the right of each song row."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioTrack, Project
from cueplayer.media.audio_loader import load_audio
from cueplayer.ui.main_window import MainWindow, SetlistWidget

ROOT = Path(__file__).resolve().parents[2]
LTC_LEFT_FIXTURE = ROOT / "fixtures" / "media" / "中文測試" / "LTC左_音樂右_測試.wav"


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _ltc_item(window: MainWindow, song_index: int = 0):
    for row in range(window.song_list.rowCount()):
        if window.song_list.row_song_index(row) == song_index:
            return window.song_list.item(row, SetlistWidget.COL_LTC)
    return None


def test_setlist_ltc_column_shows_left_channel(app: QApplication) -> None:
    assert LTC_LEFT_FIXTURE.is_file()
    window = MainWindow(Project.create("LTC Indicator"))
    song = window.project.songs[0]
    song.audio_tracks = [
        AudioTrack(id="main", name="stripe", path=LTC_LEFT_FIXTURE, role="main")
    ]
    key = window._audio_cache_key(LTC_LEFT_FIXTURE)
    assert key is not None
    window._audio_ltc_cache[key] = 0
    window._rebuild_song_list(select_indexes=[0])

    item = _ltc_item(window, 0)
    assert item is not None
    assert item.data(SetlistWidget.ROLE_LTC_CHANNEL) == 0
    assert "Left" in item.toolTip()


def test_ltc_detect_populates_setlist_badge(app: QApplication) -> None:
    assert LTC_LEFT_FIXTURE.is_file()
    buffer = load_audio(LTC_LEFT_FIXTURE)
    window = MainWindow(Project.create("LTC Detect"))
    song = window.project.songs[0]
    song.audio_tracks = [
        AudioTrack(id="main", name="stripe", path=LTC_LEFT_FIXTURE, role="main")
    ]
    window._store_audio_cache(LTC_LEFT_FIXTURE, buffer, write_disk=False, schedule_ltc=True)

    deadline = time.monotonic() + 5.0
    key = window._audio_cache_key(LTC_LEFT_FIXTURE)
    while time.monotonic() < deadline:
        app.processEvents()
        if key in window._audio_ltc_cache:
            break
        time.sleep(0.02)

    assert window._audio_ltc_cache.get(key) == 0
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        app.processEvents()
        item = _ltc_item(window, 0)
        if item is not None and item.data(SetlistWidget.ROLE_LTC_CHANNEL) == 0:
            break
        time.sleep(0.02)

    item = _ltc_item(window, 0)
    assert item is not None
    assert item.data(SetlistWidget.ROLE_LTC_CHANNEL) == 0
