"""Video Clip editor supports direct long-source in/out entry."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog

from cueplayer.domain.models import VideoClip
from cueplayer.ui.video_clip_dialog import VideoClipEditDialog


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _clip() -> VideoClip:
    return VideoClip.create(
        "Long rehearsal",
        Path("長影片.mp4"),
        start_seconds=12.0,
        duration_seconds=180.0,
        source_duration_seconds=3900.0,
    )


def test_accepts_fifty_to_fifty_three_minute_source_range(app: QApplication) -> None:
    dialog = VideoClipEditDialog(_clip())
    dialog.timeline_start.setText("00:05.500")
    dialog.source_in.setText("00:50:00.000")
    dialog.source_out.setText("00:53:00.000")

    dialog._validate_and_accept()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.values() == pytest.approx((5.5, 3000.0, 3180.0))
    assert dialog.duration.text() == "03:00.000"


def test_rejects_source_out_beyond_media_duration(app: QApplication) -> None:
    dialog = VideoClipEditDialog(_clip())
    dialog.source_in.setText("01:00:00.000")
    dialog.source_out.setText("01:10:00.000")

    with patch("cueplayer.ui.video_clip_dialog.QMessageBox.warning") as warning:
        dialog._validate_and_accept()

    assert dialog.result() != QDialog.DialogCode.Accepted
    warning.assert_called_once()


def test_rejects_timeline_start_beyond_song_length(app: QApplication) -> None:
    dialog = VideoClipEditDialog(_clip(), timeline_duration=185.0)
    dialog.timeline_start.setText("03:05.001")

    with patch("cueplayer.ui.video_clip_dialog.QMessageBox.warning") as warning:
        dialog._validate_and_accept()

    assert dialog.result() != QDialog.DialogCode.Accepted
    warning.assert_called_once_with(
        dialog,
        "Invalid Video Clip Time",
        "Timeline Start cannot exceed the song length (03:05.000).",
    )
    assert dialog.values()[0] == pytest.approx(185.001)


def test_accepts_timeline_start_at_song_end(app: QApplication) -> None:
    dialog = VideoClipEditDialog(_clip(), timeline_duration=185.0)
    dialog.timeline_start.setText("03:05.000")

    dialog._validate_and_accept()

    assert dialog.result() == QDialog.DialogCode.Accepted
