"""Discontinuous seek (Mark / cue) must keep presenting after bootstrap."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.playback.video_sync import VideoPipelineState, VideoSyncController


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app  # type: ignore[return-value]


def _shutdown(controller: VideoSyncController) -> None:
    try:
        controller._async_pool.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass


def test_note_discontinuous_seek_clears_presentation_floor(qapp: QApplication) -> None:
    del qapp
    controller = VideoSyncController()
    try:
        controller._playing = True
        controller._video_output_active = True
        controller._last_presented_song_seconds = 1000.0
        controller._last_position_seconds = 1000.0
        controller._pipeline_state = VideoPipelineState.PLAYBACK
        scheduled: list[float] = []

        def _sched(t: float, **kwargs) -> None:  # noqa: ANN003
            scheduled.append(float(t))

        controller._schedule_playback_target = _sched  # type: ignore[method-assign]
        controller._invalidate_async_requests = MagicMock()  # type: ignore[method-assign]

        controller.note_discontinuous_seek(
            947.8,
            from_seconds=1000.0,
            input_source="mark_object",
            playing=True,
        )
        assert controller._last_presented_song_seconds is None
        assert controller._min_present_seconds == pytest.approx(947.8)
        assert controller._seek_jump_input_source == "mark_object"
        assert controller._seek_jump_mono is not None
        assert scheduled and scheduled[-1] == pytest.approx(947.8)
        controller._invalidate_async_requests.assert_called()
    finally:
        _shutdown(controller)


def test_seek_jump_stale_frames_do_not_rearm_floor(qapp: QApplication) -> None:
    del qapp
    controller = VideoSyncController()
    try:
        controller._playing = True
        controller._video_output_active = True
        controller._pipeline_state = VideoPipelineState.PLAYBACK
        controller._last_position_seconds = 947.8
        controller.note_discontinuous_seek(
            947.8,
            from_seconds=1018.0,
            input_source="mark_object",
            playing=True,
        )
        # Stale pre-seek frame far from engine target must be dropped.
        frame = np.zeros((8, 8, 3), dtype=np.uint8)
        controller._on_async_frame_ready(
            int(controller._async_req_gen),
            1018.0,
            frame,
            "play",
            "",
            0,
            -1,
        )
        assert controller._last_presented_song_seconds is None
        # In-target frame advances liveness.
        controller._on_async_frame_ready(
            int(controller._async_req_gen),
            947.8,
            frame,
            "play",
            "",
            0,
            -1,
        )
        assert controller._last_presented_song_seconds == pytest.approx(947.8)
        assert controller._seek_liveness_presented >= 1
    finally:
        _shutdown(controller)


def test_backward_seek_allows_frames_below_prior_last_presented(
    qapp: QApplication,
) -> None:
    """Regression: Mark jump used to fail newer_already_presented forever."""
    del qapp
    controller = VideoSyncController()
    try:
        song = Song.create("S")
        clip = VideoClip.create(
            name="v",
            path=Path("v.mp4"),
            start_seconds=0.0,
            duration_seconds=2000.0,
        )
        song.add_video_clip(clip)
        controller.set_song(song)
        controller._playing = True
        controller._video_output_active = True
        controller._set_pipeline_state(VideoPipelineState.PLAYBACK)
        controller._last_presented_song_seconds = 1018.0
        controller._last_position_seconds = 1018.0

        controller.note_discontinuous_seek(
            947.0,
            from_seconds=1018.0,
            input_source="mark_object",
            playing=True,
        )
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        # Without the floor clear, 947 < 1018 would be dropped.
        controller._last_position_seconds = 947.05
        controller._on_async_frame_ready(
            int(controller._async_req_gen),
            947.0,
            frame,
            "play",
            "",
            0,
            -1,
        )
        assert controller._last_presented_song_seconds == pytest.approx(947.0)
        assert controller._seek_liveness_presented >= 1
    finally:
        _shutdown(controller)
