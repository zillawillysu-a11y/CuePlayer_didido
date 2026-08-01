"""Playhead stays smooth while Video Track work is throttled on the UI thread."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.playback import video_sync as video_sync_mod
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_play_decode_cap_leaves_headroom_for_timeline() -> None:
    assert video_sync_mod._MAX_PLAY_DECODE_HZ <= 20.0
    assert video_sync_mod._MAX_PLAY_DECODE_HZ >= 12.0


def test_view_changed_throttled_while_playing(app: QApplication) -> None:
    song = Song.create("Jank")
    widget = TimelineWidget()
    widget.set_song(song)
    widget.resize(800, 400)
    widget.set_playing(True)

    events: list[int] = []
    widget.view_changed.connect(lambda: events.append(1))

    # Simulate ~60 Hz playhead ticks without scroll follow movement.
    widget._auto_scroll = False
    for i in range(30):
        widget.set_position(i * 0.016)

    # Playhead updates every tick via update(), but overview mirror is ~15 Hz.
    assert 1 <= len(events) <= 12
