"""Video Music-lane stand-in should survive leaving the song and coming back."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project, VideoClip
from cueplayer.media.audio_loader import AudioBuffer
from cueplayer.ui.main_window import MainWindow
from tests.media.test_video_audio_loader import _make_clip_with_tone


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_video_standin_restores_from_cache_on_reactivate(
    app: QApplication, tmp_path: Path
) -> None:
    path = tmp_path / "standin.mp4"
    _make_clip_with_tone(path, seconds=0.6)
    project = Project.create("波形快取")
    song_a = project.songs[0]
    song_a.name = "Video"
    clip = VideoClip.create(
        name="v",
        path=path,
        start_seconds=0.0,
        duration_seconds=0.6,
        source_duration_seconds=0.6,
    )
    song_a.video_clips = [clip]
    song_a.duration_seconds = 0.6
    song_b = project.new_song("Other")
    project.songs.append(song_b)

    window = MainWindow(project=project)
    fake = AudioBuffer(
        path=path,
        sample_rate=400,
        samples=np.zeros((240, 2), dtype=np.float32),
        mono=np.zeros(240, dtype=np.float32),
        peak_levels=[],
    )
    key = window._video_standin_cache_key(clip, timeline_duration=0.6)
    assert key is not None
    window._video_standin_cache[key] = fake

    window._activate_song(1, stop_playback=True)
    with patch.object(window, "_audio_load_executor") as executor:
        window._activate_song(0, stop_playback=True)
        executor.submit.assert_not_called()
    assert window.timeline._audio is fake
    assert window.timeline.audio_loading() is False
