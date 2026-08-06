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
    rid = int(controller._async_req_id) + 1
    controller._async_req_id = rid
    controller._last_position_seconds = float(t)
    controller._note_resume_queued_result(
        gen=gen,
        request_id=rid,
        song_time=float(t),
        media_session=int(controller._media_session_gen),
        scrub_session=int(controller._scrub_session_gen),
        valid_frame=True,
    )
    controller._on_async_frame_ready(
        gen,
        float(t),
        np.full((8, 8, 3), 90, dtype=np.uint8),
        "play",
        "",
        -1,
        rid,
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


def test_recovery_too_late_bootstrap_accepts_then_catchup(
    app: QApplication, red_clip_path: Path
) -> None:
    """UI-delayed resume frame is accepted as bootstrap; catch up to engine."""
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
        controller._async_req_gen += 1
        gen = controller._async_req_gen
        # Mark as WAITING_FRAME queued for this resume txn.
        controller._note_resume_queued_frame(
            gen=gen,
            request_id=99,
            song_time=1.0,
            media_session=int(controller._media_session_gen),
            scrub_session=int(controller._scrub_session_gen),
            valid_frame=True,
        )
        # Engine advanced while UI callback was delayed.
        controller._last_position_seconds = 2.0
        controller._on_async_frame_ready(
            gen,
            1.0,
            np.full((8, 8, 3), 40, dtype=np.uint8),
            "play",
            "",
            -1,
            99,
        )
        assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
        snap = perf_diag.snapshot()["counters"]
        assert snap.get("video.scrub.resume_bootstrap_late_accept", 0) >= 1
        assert snap.get("video.scrub.resume_waiting_frame_presented", 0) >= 1
        assert snap.get("video.scrub.resume_recovery_started", 0) == snap.get(
            "video.scrub.resume_recovery_completed", 0
        )
        assert snap.get("video.scrub.resume_bootstrap_catchup", 0) >= 1
        assert any(abs(t - 2.0) < 1e-6 for t in scheduled)
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


def test_watchdog_defers_while_waiting_frame_beyond_deadline(
    app: QApplication, red_clip_path: Path
) -> None:
    """Qt UI callback delayed past watchdog: do not gen-bump; still present."""
    from cueplayer.diagnostics import video_sm_trace as sm_trace

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
        _enter_resume(controller, 0.6)
        # First timeout with no progress starts recovery once.
        controller._on_resume_watchdog()
        assert (
            perf_diag.snapshot()["counters"].get(
                "video.scrub.resume_recovery_started", 0
            )
            == 1
        )
        gen_before = int(controller._async_req_gen)
        # Worker finished decode → WAITING_FRAME queued (UI slot not run yet).
        controller._note_resume_queued_frame(
            gen=gen_before,
            request_id=1472,
            song_time=0.6,
            media_session=int(controller._media_session_gen),
            scrub_session=int(controller._scrub_session_gen),
            valid_frame=True,
        )
        sm_trace.set_worker_runtime(
            sm_trace.WorkerRuntime.WAITING_FRAME,
            request_id=1472,
            reason="test_delay_ui",
        )
        # Multiple watchdog fires past the deadline must NOT bump generation.
        for _ in range(5):
            controller._on_resume_watchdog()
        assert int(controller._async_req_gen) == gen_before
        snap_mid = perf_diag.snapshot()["counters"]
        assert (
            snap_mid.get("video.scrub.resume_watchdog_deferred_for_waiting_frame", 0)
            >= 5
        )
        # No additional recovery invalidate loop.
        assert snap_mid.get("video.scrub.resume_recovery_started", 0) == 1
        # Deliver the delayed UI callback (engine advanced meanwhile).
        controller._last_position_seconds = 1.2
        controller._on_async_frame_ready(
            gen_before,
            0.6,
            np.full((8, 8, 3), 88, dtype=np.uint8),
            "play",
            "",
            -1,
            1472,
        )
        assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
        assert (
            controller._playback_handoff
            == PlaybackDecoderHandoff.PLAYBACK_DECODER_READY
        )
        snap = perf_diag.snapshot()["counters"]
        assert snap.get("video.scrub.resume_waiting_frame_presented", 0) >= 1
        assert snap.get("video.scrub.resume_bootstrap_late_accept", 0) >= 1
        assert snap.get("video.scrub.resume_recovery_started", 0) == snap.get(
            "video.scrub.resume_recovery_completed", 0
        )
        assert snap.get("video.scrub.resume_started", 0) == (
            snap.get("video.scrub.resume_completed", 0)
            + snap.get("video.scrub.resume_recovered", 0)
        )
    _shutdown_ctrl(controller)
    perf_diag.set_enabled(False)
