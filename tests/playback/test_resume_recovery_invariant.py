"""RESUME recovery completes only after a current valid playback frame."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import Song, VideoClip
from cueplayer.playback.video_sync import (
    PlaybackDecoderHandoff,
    VideoPipelineState,
    VideoSyncController,
)


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def red_clip_path(tmp_path: Path) -> Path:
    # Tiny RGB still used as a video path stand-in when decode is mocked.
    path = tmp_path / "red.png"
    try:
        from PIL import Image

        Image.new("RGB", (16, 16), (200, 20, 20)).save(path)
    except Exception:
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    return path


def _shutdown_ctrl(controller: VideoSyncController) -> None:
    controller._resume_watchdog.stop()
    controller._async_inflight = False
    try:
        controller._async_pool.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass


def _enter_resume(controller: VideoSyncController, t: float) -> None:
    controller.set_scrubbing(True, was_playing=True)
    controller._scrub_preload_timer.stop()
    controller._scrub_preview_timer.stop()
    controller.update_position(t, source="scrub")
    controller._scrubbing = False
    controller._scrub_preview_timer.stop()
    controller._scrub_pause_timer.stop()
    controller._release_target_song_time = float(t)
    controller._release_target_media_time = float(t)
    controller._min_present_seconds = float(t)
    controller._final_land_transaction_id = controller._scrub_transaction_id
    controller._pre_scrub_was_playing = True
    controller._decoder_position_established = True
    controller._final_land_pending = False
    controller._async_inflight = False
    controller._last_valid_frame = np.full((8, 8, 3), 11, dtype=np.uint8)
    controller._last_position_seconds = float(t)
    controller._enter_resume_playback()


def _present_play_frame(controller: VideoSyncController, t: float) -> None:
    controller._async_req_gen += 1
    gen = controller._async_req_gen
    controller._last_position_seconds = float(t)
    controller._on_async_frame_ready(
        gen,
        float(t),
        np.full((8, 8, 3), 90, dtype=np.uint8),
        "play",
        "",
        -1,
    )


def test_recovery_first_request_succeeds(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=str(red_clip_path), start_seconds=0.0, duration_seconds=4.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    with patch.object(controller, "_request_async_live_frame", return_value=None):
        _enter_resume(controller, 0.5)
        assert controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK
        controller._on_resume_watchdog()
        assert perf_diag.snapshot()["counters"].get(
            "video.scrub.resume_recovery_started", 0
        ) == 1
        assert controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK
        _present_play_frame(controller, 0.55)
        assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
        assert (
            controller._playback_handoff
            == PlaybackDecoderHandoff.PLAYBACK_DECODER_READY
        )
        snap = perf_diag.snapshot()["counters"]
        assert snap.get("video.scrub.resume_recovery_started", 0) == 1
        assert snap.get("video.scrub.resume_recovery_completed", 0) == 1
    _shutdown_ctrl(controller)
    perf_diag.set_enabled(False)


def test_recovery_too_late_resubmits_then_completes(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=str(red_clip_path), start_seconds=0.0, duration_seconds=4.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    scheduled: list[float] = []

    def _capture(seconds, **kwargs):  # noqa: ANN001
        scheduled.append(float(seconds))

    with patch.object(controller, "_request_async_live_frame", side_effect=_capture):
        _enter_resume(controller, 1.0)
        controller._on_resume_watchdog()
        assert controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK
        # Stale decode arrives while engine has moved ahead → too_late.
        controller._async_req_gen += 1
        gen = controller._async_req_gen
        controller._last_position_seconds = 2.0
        before = len(scheduled)
        controller._on_async_frame_ready(
            gen,
            1.0,
            np.full((8, 8, 3), 40, dtype=np.uint8),
            "play",
            "",
            -1,
        )
        assert controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK
        assert perf_diag.snapshot()["counters"].get(
            "video.scrub.resume_recovery_completed", 0
        ) == 0
        assert len(scheduled) > before  # latest target resubmitted
        assert scheduled[-1] == pytest.approx(2.0)
        # Current-generation frame at engine time completes.
        _present_play_frame(controller, 2.0)
        assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
        snap = perf_diag.snapshot()["counters"]
        assert snap.get("video.scrub.resume_recovery_started", 0) == 1
        assert snap.get("video.scrub.resume_recovery_completed", 0) == 1
        assert snap.get("video.playback.frame_drop.reason.too_late", 0) >= 1
    _shutdown_ctrl(controller)
    perf_diag.set_enabled(False)


def test_generation_mismatch_keeps_request_not_false_ready(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=str(red_clip_path), start_seconds=0.0, duration_seconds=4.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    scheduled: list[tuple[float, dict]] = []

    def _capture(seconds, **kwargs):  # noqa: ANN001
        scheduled.append((float(seconds), dict(kwargs)))

    with patch.object(controller, "_request_async_live_frame", side_effect=_capture):
        _enter_resume(controller, 0.7)
        controller._on_resume_watchdog()
        stale_gen = int(controller._async_req_gen)
        # Decoder replacement / invalidate advances generation.
        controller._invalidate_async_requests()
        controller._last_position_seconds = 0.85
        before = len(scheduled)
        controller._on_async_frame_ready(
            stale_gen,
            0.7,
            np.full((8, 8, 3), 55, dtype=np.uint8),
            "play",
            "",
            -1,
        )
        assert controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK
        assert (
            controller._playback_handoff
            != PlaybackDecoderHandoff.PLAYBACK_DECODER_READY
        )
        assert len(scheduled) > before
        # Idle worker during RESUME must receive current target.
        controller._async_inflight = False
        controller._play_pending_seconds = None
        controller._ensure_resume_target_while_idle()
        assert any(abs(t - 0.85) < 1e-6 for t, _ in scheduled)
        _present_play_frame(controller, 0.85)
        assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
        snap = perf_diag.snapshot()["counters"]
        assert snap.get("video.playback.frame_drop.reason.generation_mismatch", 0) >= 1
        assert snap.get("video.scrub.resume_recovery_started", 0) == snap.get(
            "video.scrub.resume_recovery_completed", 0
        )
    _shutdown_ctrl(controller)
    perf_diag.set_enabled(False)


def test_dense_region_repeated_seek_every_resume_presents(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=str(red_clip_path), start_seconds=0.0, duration_seconds=8.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    # sparse → dense → sparse → dense
    targets = (0.2, 3.5, 0.4, 4.0)
    with patch.object(controller, "_request_async_live_frame", return_value=None):
        for t in targets:
            _enter_resume(controller, t)
            assert controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK
            # Simulate one recovery shot that does not false-complete.
            controller._on_resume_watchdog()
            assert controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK
            _present_play_frame(controller, t + 0.02)
            assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
            assert (
                controller._playback_handoff
                == PlaybackDecoderHandoff.PLAYBACK_DECODER_READY
            )
        snap = perf_diag.snapshot()["counters"]
        started = int(snap.get("video.scrub.resume_started", 0))
        assert started >= len(targets)
        assert int(snap.get("video.scrub.resume_recovery_started", 0)) == int(
            snap.get("video.scrub.resume_recovery_completed", 0)
        )
        # No false-ready recovery completions without frames.
        assert int(snap.get("video.scrub.resume_complete_rejected", 0)) == 0
    _shutdown_ctrl(controller)
    perf_diag.set_enabled(False)
