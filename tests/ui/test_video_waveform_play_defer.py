"""Video waveform-ready must invalidate the static backdrop even while playing.

Previously ready was deferred until pause; with always-static PLAYING/PAUSED
caches that left an empty bake stuck for the whole play session.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_video_waveform_ready_invalidates_backdrop_while_playing(
    app: QApplication, tmp_path: Path
) -> None:
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
    widget._scrub_backdrop = QPixmap(8, 8)  # noqa: SLF001
    rev0 = widget._video_waveform_revision  # noqa: SLF001

    widget._apply_video_waveform_ready()  # noqa: SLF001

    assert widget._video_waveform_pending_refresh is False  # noqa: SLF001
    assert widget._scrub_backdrop is None  # noqa: SLF001
    assert widget._video_waveform_revision == rev0 + 1  # noqa: SLF001
    assert widget._video_waveform_baked_revision == -1  # noqa: SLF001
