"""Queued-result ownership, timeline-gap resume, and PLAYBACK decode budget."""

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
    DisplaySource,
    PreviewVideoState,
    VideoPipelineState,
    VideoSyncController,
)


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def red_clip_path(tmp_path: Path) -> Path:
    path = tmp_path / "red.png"
    try:
        from PIL import Image

        Image.new("RGB", (16, 16), (200, 20, 20)).save(path)
    except Exception:
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    return path


def _shutdown_ctrl(controller: VideoSyncController) -> None:
    controller._resume_watchdog.stop()
    controller._play_budget_timer.stop()
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


def test_playing_scrub_release_into_timeline_gap_no_waiting_frame(
    app: QApplication, red_clip_path: Path
) -> None:
    """Gap at Audio-clock target → intentional gap; no WAITING_FRAME / recovery."""
    song = Song.create("Song")
    # Clip only covers 0–2s; scrub-release into a gap at 5s.
    song.add_video_clip(
        VideoClip.create(
            name="red", path=str(red_clip_path), start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    with patch.object(controller, "_request_async_live_frame", return_value=None):
        controller.set_scrubbing(True, was_playing=True)
        controller._scrub_preload_timer.stop()
        controller._scrub_preview_timer.stop()
        controller._pre_scrub_was_playing = True
        controller._playing = True
        controller._release_target_song_time = 5.0
        controller._release_target_media_time = None
        controller._last_position_seconds = 5.0
        controller._final_land_transaction_id = 1
        controller._enter_resume_playback()
        assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
        assert not controller._resume_pending
        assert not controller._resume_has_waiting_frame()
        assert controller._preview_video_state == PreviewVideoState.VIDEO_TIMELINE_GAP
        assert controller._display_source == DisplaySource.INTENTIONAL_GAP
        snap = perf_diag.snapshot()["counters"]
        assert snap.get("video.scrub.resume_not_required_timeline_gap", 0) >= 1
        assert snap.get("video.scrub.resume_terminal.intentional_gap", 0) >= 1
        assert snap.get("video.scrub.resume_started", 0) == 0
        assert snap.get("video.scrub.resume_recovery_started", 0) == 0
        assert snap.get("video.scrub.queued_result_emitted", 0) == 0
    _shutdown_ctrl(controller)
    perf_diag.set_enabled(False)


def test_empty_decode_acks_queued_no_phantom_waiting(
    app: QApplication, red_clip_path: Path
) -> None:
    """Valid clip + empty decode: ack queued result; resubmit; no WAITING_FRAME."""
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
        _enter_resume(controller, 0.5)
        assert controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK
        gen = int(controller._async_req_gen)
        rid = 501
        controller._note_resume_queued_result(
            gen=gen,
            request_id=rid,
            song_time=0.5,
            media_session=int(controller._media_session_gen),
            scrub_session=int(controller._scrub_session_gen),
            valid_frame=False,
            empty_reason="decode_empty",
        )
        assert not controller._resume_has_waiting_frame()
        before = len(scheduled)
        controller._on_async_frame_ready(
            gen, 0.5, None, "play", "decode_empty", -1, rid
        )
        assert controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK
        assert not controller._resume_has_waiting_frame()
        snap = perf_diag.snapshot()["counters"]
        assert snap.get("video.scrub.queued_result_emitted", 0) >= 1
        assert snap.get("video.scrub.queued_result_acknowledged", 0) >= 1
        assert snap.get("video.scrub.queued_invalid_result", 0) >= 1
        assert snap.get("video.scrub.resume_invalid_decode_resubmit", 0) >= 1
        assert len(scheduled) > before
        # Watchdog must not defer for phantom WAITING_FRAME.
        controller._on_resume_watchdog()
        snap2 = perf_diag.snapshot()["counters"]
        assert snap2.get(
            "video.scrub.resume_watchdog_deferred_for_waiting_frame", 0
        ) == 0
    _shutdown_ctrl(controller)
    perf_diag.set_enabled(False)


def test_valid_frame_delayed_ui_still_presented(
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
        _enter_resume(controller, 0.8)
        gen = int(controller._async_req_gen)
        rid = 777
        controller._note_resume_queued_result(
            gen=gen,
            request_id=rid,
            song_time=0.8,
            media_session=int(controller._media_session_gen),
            scrub_session=int(controller._scrub_session_gen),
            valid_frame=True,
        )
        assert controller._resume_has_waiting_frame()
        controller._on_resume_watchdog()
        assert (
            perf_diag.snapshot()["counters"].get(
                "video.scrub.resume_watchdog_deferred_for_waiting_frame", 0
            )
            >= 1
        )
        controller._on_async_frame_ready(
            gen,
            0.8,
            np.full((8, 8, 3), 70, dtype=np.uint8),
            "play",
            "",
            -1,
            rid,
        )
        assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
        snap = perf_diag.snapshot()["counters"]
        assert snap.get("video.scrub.queued_result_emitted", 0) == snap.get(
            "video.scrub.queued_result_acknowledged", 0
        )
        assert snap.get("video.scrub.resume_waiting_frame_presented", 0) >= 1
    _shutdown_ctrl(controller)
    perf_diag.set_enabled(False)


def test_old_queued_callback_does_not_clear_newer_request(
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
        _enter_resume(controller, 1.0)
        gen = int(controller._async_req_gen)
        old_id, new_id = 10, 20
        controller._note_resume_queued_result(
            gen=gen,
            request_id=old_id,
            song_time=1.0,
            media_session=int(controller._media_session_gen),
            scrub_session=int(controller._scrub_session_gen),
            valid_frame=False,
            empty_reason="decode_empty",
        )
        controller._note_resume_queued_result(
            gen=gen,
            request_id=new_id,
            song_time=1.05,
            media_session=int(controller._media_session_gen),
            scrub_session=int(controller._scrub_session_gen),
            valid_frame=True,
        )
        assert controller._resume_has_waiting_frame()
        # Old invalid callback arrives first — must not clear newer valid wait.
        controller._on_async_frame_ready(
            gen, 1.0, None, "play", "decode_empty", -1, old_id
        )
        assert controller._resume_has_waiting_frame()
        newer = controller._resume_queued_results.get(new_id)
        assert newer is not None and not newer.acknowledged and newer.valid_frame
        controller._on_async_frame_ready(
            gen,
            1.05,
            np.full((8, 8, 3), 33, dtype=np.uint8),
            "play",
            "",
            -1,
            new_id,
        )
        assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
    _shutdown_ctrl(controller)
    perf_diag.set_enabled(False)


def test_stable_playback_budget_defers_idle_ticks(
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
    controller._playing = True
    controller._pipeline_state = VideoPipelineState.PLAYBACK
    controller._last_decode_time = 1e12  # far future → always within budget window
    # Force last_decode_time recent relative to monotonic.
    from time import monotonic

    controller._last_decode_time = monotonic()
    controller._async_inflight = False
    submitted: list[float] = []

    def _capture(seconds, **kwargs):  # noqa: ANN001
        submitted.append(float(seconds))

    with patch.object(controller, "_request_async_live_frame", side_effect=_capture):
        # Many 60 Hz ticks within one budget period → one pending, no flood.
        for i in range(10):
            controller._schedule_playback_target(
                1.0 + i * 0.016,
                scheduler="update_position_playing",
                force=False,
            )
        assert len(submitted) == 0
        assert controller._play_pending_seconds is not None
        snap = perf_diag.snapshot()["counters"] if perf_diag.is_enabled() else {}
        # Enable and re-run with counters.
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller._last_decode_time = monotonic()
    controller._play_pending_seconds = None
    with patch.object(controller, "_request_async_live_frame", side_effect=_capture):
        for i in range(10):
            controller._schedule_playback_target(
                2.0 + i * 0.016,
                scheduler="update_position_playing",
                force=False,
            )
        assert len(submitted) == 0
        assert perf_diag.snapshot()["counters"].get(
            "video.playback.budget_deferred", 0
        ) >= 1
        # Force / RESUME bypass budget.
        controller._schedule_playback_target(
            3.0, scheduler="resume_idle_resubmit", force=True
        )
        assert any(abs(t - 3.0) < 1e-6 for t in submitted)
    _shutdown_ctrl(controller)
    perf_diag.set_enabled(False)
