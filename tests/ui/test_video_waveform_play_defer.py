"""Defer video waveform backdrop rebuild while playing."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_video_waveform_ready_defers_backdrop_while_playing(app: QApplication, tmp_path) -> None:
    del app
    media = tmp_path / "clip.mov"
    media.write_bytes(b"fake")
    song = Song.create("Vid")
    clip = VideoClip.create(
        path=media,
        name="Clip",
        start_seconds=0.0,
        duration_seconds=4.0,
        media_kind="video",
    )
    song.video_clips.append(clip)

    widget = TimelineWidget()
    widget.set_song(song)
    widget.set_playing(True)
    widget._scrub_backdrop = object()  # type: ignore[assignment]

    widget._apply_video_waveform_ready()

    assert widget._video_waveform_pending_refresh is True
    assert widget._scrub_backdrop is not None

    widget.set_playing(False)
    assert widget._video_waveform_pending_refresh is False
    assert widget._scrub_backdrop is None
