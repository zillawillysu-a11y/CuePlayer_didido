"""LtcClipEditDialog validation (Phase 3): timeline overlap blocked, TC conflicts warned.

Error paths are asserted through ``_validation_result`` (the message box is
modal and would hang offscreen tests); the accept path is exercised directly.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog

from cueplayer.domain.ltc_clips import add_ltc_clip
from cueplayer.domain.models import Song
from cueplayer.ui.ltc_clip_dialog import LtcClipEditDialog


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _song(with_clip: bool = False) -> Song:
    song = Song.create("LTC dlg")
    song.duration_seconds = 60.0
    if with_clip:
        add_ltc_clip(
            song,
            timeline_start_seconds=10.0,
            duration_seconds=20.0,
            start_timecode="01:00:05:00",
        )
    return song


def test_values_round_trip(app: QApplication) -> None:  # noqa: ANN001
    dialog = LtcClipEditDialog(_song(), default_start_seconds=12.0)
    dialog.timeline_start.setText("00:15.000")
    dialog.duration.setText("00:10.000")
    dialog.start_timecode.setText("01:00:10:00")
    dialog._validate_and_accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.values() == (15.0, 10.0, "01:00:10:00")


def test_unparseable_fields_report_error(app: QApplication) -> None:  # noqa: ANN001
    dialog = LtcClipEditDialog(_song())
    dialog.start_timecode.setText("not-a-timecode")
    error, _warning, _ = dialog._validation_result()
    assert error


def test_end_after_song_end_is_rejected(app: QApplication) -> None:  # noqa: ANN001
    dialog = LtcClipEditDialog(_song())
    dialog.timeline_start.setText("00:55.000")
    dialog.duration.setText("00:10.000")
    error, _warning, _ = dialog._validation_result()
    assert error
    assert "after the song ends" in error


def test_timeline_overlap_is_rejected(app: QApplication) -> None:  # noqa: ANN001
    dialog = LtcClipEditDialog(_song(with_clip=True))
    # Existing clip spans 10–30s; candidate 20–25 overlaps.
    dialog.timeline_start.setText("00:20.000")
    dialog.duration.setText("00:05.000")
    error, _warning, _ = dialog._validation_result()
    assert error
    assert "Overlaps" in error


def test_edit_existing_clip_can_keep_own_range(app: QApplication) -> None:  # noqa: ANN001
    song = _song(with_clip=True)
    clip = song.ltc_clips[0]
    dialog = LtcClipEditDialog(song, clip=clip)
    # Same range as before must be fine (no self-overlap error).
    dialog.timeline_start.setText("00:10.000")
    dialog.duration.setText("00:20.000")
    dialog.start_timecode.setText("01:00:05:00")
    dialog._validate_and_accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.values() == (10.0, 20.0, "01:00:05:00")


def test_overlapping_tc_range_is_allowed_with_warning(app: QApplication) -> None:  # noqa: ANN001
    # Existing clip: 10–30s sending 01:00:05:00 → ends 01:00:15:00 @30fps.
    dialog = LtcClipEditDialog(_song(with_clip=True))
    # Candidate 30–40s starts at 01:00:10:00 (inside the existing TC range) —
    # timeline ranges touch at 30s (no overlap) but the TC ranges overlap.
    dialog.timeline_start.setText("00:30.000")
    dialog.duration.setText("00:10.000")
    dialog.start_timecode.setText("01:00:10:00")
    error, warning, _ = dialog._validation_result()
    assert not error
    assert warning  # surfaced as a warning, not an error
    dialog._validate_and_accept()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_backwards_tc_range_is_allowed_with_warning(app: QApplication) -> None:  # noqa: ANN001
    # Existing clip 10–30s: 01:00:05:00 → 01:00:15:00.
    dialog = LtcClipEditDialog(_song(with_clip=True))
    # Candidate 40–50s starts at 01:00:00:00 (backwards relative to the first).
    dialog.timeline_start.setText("00:40.000")
    dialog.duration.setText("00:10.000")
    dialog.start_timecode.setText("01:00:00:00")
    error, warning, _ = dialog._validation_result()
    assert not error
    assert warning
    dialog._validate_and_accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
