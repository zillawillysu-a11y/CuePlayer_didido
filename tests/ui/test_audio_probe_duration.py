"""Importing audio must set song duration from metadata before waveform decode."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow
from cueplayer.ui.song_edit_dialog import SongDraft


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_apply_draft_probes_audio_duration_immediately(
    app: QApplication, tmp_path: Path
) -> None:
    path = tmp_path / "longish.wav"
    sr = 16000
    seconds = 12.0
    sf.write(
        str(path),
        (np.random.default_rng(1).standard_normal((int(sr * seconds), 2)) * 0.05).astype(
            np.float32
        ),
        sr,
    )
    window = MainWindow(project=Project.create("時長探測"))
    song = window.current_song
    assert song.duration_seconds == pytest.approx(60.0)

    draft = SongDraft(
        name="Long",
        setlist_number=1.0,
        ma_export_name="Long",
        start_timecode="01:00:00:00",
        fps=30.0,
        audio_path=path,
    )
    window._apply_draft_to_song(song, draft)
    assert song.duration_seconds == pytest.approx(seconds, abs=0.1)
    assert window.engine.duration == pytest.approx(seconds, abs=0.1)
