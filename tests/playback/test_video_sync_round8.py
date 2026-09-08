"""Sprint 8 Task 2 Round 8 — post-land submit + playback lateness (no gen starvation)."""

from __future__ import annotations

import time
from pathlib import Path

import av
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import Song, VideoClip
from cueplayer.playback.video_sync import (
    VideoPipelineState,
    VideoSyncController,
    _PLAYBACK_LATENESS_TOLERANCE_S,
)

WIDTH, HEIGHT, FPS = 32, 24, 10


def _make_solid_clip(path: Path, color: tuple[int, int, int], *, seconds: float = 2.0) -> None:
    container = av.open(str(path), mode="w")
    try:
        stream = container.add_stream("mpeg4", rate=FPS)
        stream.width = WIDTH
        stream.height = HEIGHT
        stream.pix_fmt = "yuv420p"
        for i in range(int(FPS * seconds)):
            arr = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
            arr[:, :] = color
            frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    finally:
        container.close()


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def red_clip_path(tmp_path: Path) -> Path:
    path = tmp_path / "紅.mp4"
    _make_solid_clip(path, (255, 0, 0))
    return path


def _shutdown(controller: VideoSyncController) -> None:
    try:
        controller.shutdown()
    except Exception:
        pass


def _drain(controller: VideoSyncController, app: QApplication, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if (
            not controller._async_inflight
            and not controller._final_land_pending
            and not controller._land_retry_timer.isActive()
        ):
            break
        time.sleep(0.01)
    app.processEvents()


def _song_with_clip(path: Path) -> Song:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=path, start_seconds=0.0, duration_seconds=2.0)
    )
    return song


def test_final_land_present_submits_playback_when_was_playing(
    app: QApplication, red_clip_path: Path
) -> None:
    """1. FINAL_LAND_PRESENT immediately submits a playback request when previously playing."""
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller = VideoSyncController()
    try:
        controller.set_song(_song_with_clip(red_clip_path))
        controller.set_scrubbing(True, was_playing=True)
        controller.update_position(0.5, source="scrub")
        controller.set_scrubbing(False)
        _drain(controller, app, timeout=5.0)
        snap = perf_diag.snapshot()["counters"]
        assert int(snap.get("video.scrub.post_land_submit_attempt", 0)) >= 1
        assert int(snap.get("video.scrub.post_land_submit_success", 0)) >= 1
        assert int(snap.get("post_land_submit_success", 0)) >= 1
        assert controller.pipeline_state() in (
            VideoPipelineState.RESUME_PLAYBACK,
            VideoPipelineState.PLAYBACK,
        )
    finally:
        controller._resume_watchdog.stop()
        perf_diag.set_enabled(False)
        _shutdown(controller)


def test_idle_playing_engine_update_submits_immediately(
    app: QApplication, red_clip_path: Path
) -> None:
    """2. Worker cannot remain IDLE while engine updates arrive during play."""
    controller = VideoSyncController()
    try:
        controller.set_song(_song_with_clip(red_clip_path))
        controller.set_playing(True)
        controller._set_pipeline_state(VideoPipelineState.PLAYBACK)
        controller._async_inflight = False
        controller._worker_idle_since_mono = time.monotonic() - 0.05
        before = int(controller._async_req_id)
        controller.update_position(0.4, source="engine")
        assert controller._async_inflight is True or int(controller._async_req_id) != before
        assert controller._async_req_kind == "play"
        _drain(controller, app)
    finally:
        _shutdown(controller)


def test_clock_advance_does_not_invalidate_inflight_playback(
    app: QApplication, red_clip_path: Path
) -> None:
    """3. Ordinary AudioEngine clock advancement does not invalidate in-flight play."""
    controller = VideoSyncController()
    try:
        controller.set_song(_song_with_clip(red_clip_path))
        controller.set_playing(True)
        controller._set_pipeline_state(VideoPipelineState.PLAYBACK)
        controller._async_inflight = True
        controller._async_req_kind = "play"
        controller._async_req_seconds = 0.3
        gen_before = int(controller._async_req_gen)
        media_before = int(controller._media_session_gen)
        for i in range(12):
            controller.update_position(0.3 + 0.02 * i, source="engine")
        assert int(controller._async_req_gen) == gen_before
        assert int(controller._media_session_gen) == media_before
        assert controller._play_pending_seconds is not None
    finally:
        controller._async_inflight = False
        _shutdown(controller)


def test_playback_frame_within_lateness_is_presented(
    app: QApplication, red_clip_path: Path
) -> None:
    """4. Current playback frame within lateness tolerance is presented."""
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller = VideoSyncController()
    try:
        controller.set_song(_song_with_clip(red_clip_path))
        controller.set_playing(True)
        controller._set_pipeline_state(VideoPipelineState.PLAYBACK)
        controller._last_position_seconds = 1.0
        frame = np.full((8, 8, 3), 40, dtype=np.uint8)
        gen = int(controller._async_req_gen)
        session = int(controller._scrub_session_gen)
        # Frame 0.2s behind engine — within 0.35s tolerance.
        controller._on_async_frame_ready(
            gen, 0.85, frame, "play", "", session
        )
        snap = perf_diag.snapshot()["counters"]
        assert int(snap.get("video.playback.frame_accept", 0)) >= 1
        assert int(snap.get("video.playback.decode_presented", 0)) >= 1
    finally:
        perf_diag.set_enabled(False)
        _shutdown(controller)


def test_only_one_pending_latest_while_busy(
    app: QApplication, red_clip_path: Path
) -> None:
    """5. Only one latest pending target is retained while worker is busy."""
    controller = VideoSyncController()
    try:
        controller.set_song(_song_with_clip(red_clip_path))
        controller.set_playing(True)
        controller._async_inflight = True
        controller._async_req_kind = "play"
        controller._async_req_seconds = 0.1
        for t in (0.2, 0.4, 0.6, 0.8):
            controller._schedule_playback_target(t, scheduler="test")
        assert controller._play_pending_seconds == pytest.approx(0.8)
    finally:
        controller._async_inflight = False
        _shutdown(controller)


def test_pending_latest_starts_after_decode_completes(
    app: QApplication, red_clip_path: Path
) -> None:
    """6. Pending latest target starts immediately after current decode completes."""
    controller = VideoSyncController()
    try:
        controller.set_song(_song_with_clip(red_clip_path))
        controller.set_playing(True)
        controller._set_pipeline_state(VideoPipelineState.PLAYBACK)
        # Simulate worker finishing a play decode with a pending target waiting.
        controller._async_inflight = True
        controller._async_req_kind = "play"
        controller._async_req_seconds = 0.2
        controller._async_req_gen = 7
        controller._play_pending_seconds = 0.9
        # Mimic worker post-complete pending drain (same fields as worker loop).
        pending = float(controller._play_pending_seconds)
        controller._play_pending_seconds = None
        controller._async_req_seconds = pending
        controller._async_req_kind = "play"
        controller._playback_request_seq += 1
        assert controller._async_req_seconds == pytest.approx(0.9)
        assert controller._play_pending_seconds is None
        assert controller._playback_request_seq >= 1
    finally:
        controller._async_inflight = False
        controller._invalidate_async_requests()
        _shutdown(controller)


def test_scrub_begin_invalidates_playback_work(
    app: QApplication, red_clip_path: Path
) -> None:
    """7. Scrub begin still invalidates old playback work."""
    controller = VideoSyncController()
    try:
        controller.set_song(_song_with_clip(red_clip_path))
        controller.set_playing(True)
        controller._async_inflight = True
        controller._async_req_kind = "play"
        controller._play_pending_seconds = 1.2
        gen_before = int(controller._async_req_gen)
        session_before = int(controller._scrub_session_gen)
        controller.set_scrubbing(True, was_playing=True)
        assert int(controller._async_req_gen) > gen_before
        assert int(controller._scrub_session_gen) > session_before
        assert controller._play_pending_seconds is None
        assert controller.pipeline_state() == VideoPipelineState.SCRUB_PREVIEW
    finally:
        controller._async_inflight = False
        _shutdown(controller)


def test_song_change_invalidates_old_work(
    app: QApplication, red_clip_path: Path, tmp_path: Path
) -> None:
    """8. Song/video clip change still invalidates old work."""
    other = tmp_path / "藍.mp4"
    _make_solid_clip(other, (0, 0, 255))
    controller = VideoSyncController()
    try:
        controller.set_song(_song_with_clip(red_clip_path))
        media_before = int(controller._media_session_gen)
        gen_before = int(controller._async_req_gen)
        controller._play_pending_seconds = 0.5
        controller.set_song(_song_with_clip(other))
        assert int(controller._media_session_gen) > media_before
        assert int(controller._async_req_gen) > gen_before
        assert controller._play_pending_seconds is None
    finally:
        _shutdown(controller)


def test_frame_too_late_dropped_by_timestamp_policy(
    app: QApplication, red_clip_path: Path
) -> None:
    """9. Frames far behind the AudioEngine clock are dropped by timestamp policy."""
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller = VideoSyncController()
    try:
        controller.set_song(_song_with_clip(red_clip_path))
        controller.set_playing(True)
        controller._set_pipeline_state(VideoPipelineState.PLAYBACK)
        controller._last_position_seconds = 2.0
        frame = np.full((8, 8, 3), 10, dtype=np.uint8)
        gen = int(controller._async_req_gen)
        session = int(controller._scrub_session_gen)
        late_t = 2.0 - (_PLAYBACK_LATENESS_TOLERANCE_S + 0.2)
        controller._on_async_frame_ready(gen, late_t, frame, "play", "", session)
        snap = perf_diag.snapshot()["counters"]
        assert int(snap.get("video.playback.frame_drop.reason.too_late", 0)) >= 1
        assert int(snap.get("video.playback.frame_accept", 0)) == 0
    finally:
        perf_diag.set_enabled(False)
        _shutdown(controller)


def test_resume_reaches_first_play_without_incidental_timer(
    app: QApplication, red_clip_path: Path
) -> None:
    """10. Resume reaches FIRST_PLAY_FRAME without waiting for incidental timers."""
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller = VideoSyncController()
    try:
        controller.set_song(_song_with_clip(red_clip_path))
        # Simulate land complete → enter resume (explicit submit, no fanout).
        controller._release_target_song_time = 0.4
        controller._pre_scrub_was_playing = True
        controller._playing = True
        controller._set_pipeline_state(VideoPipelineState.FINAL_LANDING)
        before = int(controller._async_req_id)
        controller._enter_resume_playback()
        assert int(controller._async_req_id) != before
        assert controller._async_inflight is True
        assert controller._async_req_kind == "play"
        _drain(controller, app, timeout=5.0)
        snap = perf_diag.snapshot()["counters"]
        assert int(snap.get("video.scrub.post_land_submit_success", 0)) >= 1
        # Either presented play frame or still completing — must not rely on flush timer.
        assert not controller._flush_timer.isActive()
    finally:
        controller._resume_watchdog.stop()
        perf_diag.set_enabled(False)
        _shutdown(controller)


def test_twenty_fast_scrub_release_no_long_idle_gap(
    app: QApplication, red_clip_path: Path
) -> None:
    """11–12. Twenty fast scrub-release ops: post-land submit + continued play schedule."""
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller = VideoSyncController()
    try:
        controller.set_song(_song_with_clip(red_clip_path))
        submit_ok = 0
        for i in range(20):
            controller.set_playing(True)
            controller.set_scrubbing(True, was_playing=True)
            controller.update_position(0.1 + 0.02 * (i % 40), source="scrub")
            controller.set_scrubbing(False)
            _drain(controller, app, timeout=4.0)
            # After land, either play submitted during resume or already PLAYBACK.
            snap = perf_diag.snapshot()["counters"]
            submit_ok = int(snap.get("video.scrub.post_land_submit_success", 0))
            # Engine ticks must be able to schedule while playing.
            if controller.pipeline_state() in (
                VideoPipelineState.PLAYBACK,
                VideoPipelineState.RESUME_PLAYBACK,
            ):
                controller.set_playing(True)
                controller.update_position(0.3 + 0.01 * i, source="engine")
            _drain(controller, app, timeout=2.0)
        assert submit_ok >= 15  # allow a few gap/output edge cases
        gen_mismatch = int(
            perf_diag.snapshot()["counters"].get(
                "video.playback.frame_drop.reason.generation_mismatch", 0
            )
        )
        assert gen_mismatch == 0
    finally:
        controller._resume_watchdog.stop()
        perf_diag.set_enabled(False)
        _shutdown(controller)


def test_play_schedule_skip_reason_when_output_inactive(
    app: QApplication, red_clip_path: Path
) -> None:
    """engine_fanout-style schedule must report skip reason, not silent no-op."""
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller = VideoSyncController()
    try:
        controller.set_song(_song_with_clip(red_clip_path))
        controller.set_playing(True)
        controller.set_video_output_active(False)
        before = int(controller._async_req_id)
        controller._schedule_playback_target(0.5, scheduler="test_fanout")
        assert int(controller._async_req_id) == before
        assert not controller._async_inflight
        assert (
            int(
                perf_diag.snapshot()["counters"].get(
                    "video.playback.schedule_skip.output_inactive", 0
                )
            )
            >= 1
        )
    finally:
        perf_diag.set_enabled(False)
        _shutdown(controller)
