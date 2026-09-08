"""Round 7 — Video state-machine trace (diagnosis only, no pipeline fix)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import av
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.diagnostics import video_sm_trace as sm_trace
from cueplayer.domain.models import Song, VideoClip
from cueplayer.playback.video_sync import VideoPipelineState, VideoSyncController

WIDTH, HEIGHT, FPS = 32, 24, 10


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


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
def red_clip_path(tmp_path: Path) -> Path:
    path = tmp_path / "red.mp4"
    _make_solid_clip(path, (255, 0, 0))
    return path


def _clip(path: Path) -> VideoClip:
    return VideoClip.create(
        name="red", path=path, start_seconds=0.0, duration_seconds=2.0
    )


def test_sm_trace_scrub_land_resume_sequence(app: QApplication, red_clip_path: Path) -> None:
    song = Song.create("Song")
    song.add_video_clip(_clip(red_clip_path))
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    sm_trace.clear()

    def _fast(*_a, **_k):  # noqa: ANN001
        return np.full((8, 8, 3), 77, dtype=np.uint8)

    with patch.object(controller, "_request_async_live_frame") as _req:
        controller.set_scrubbing(True, was_playing=True)
        controller._scrub_preload_timer.stop()
        controller._scrub_preview_timer.stop()
        names = [e["event"] for e in sm_trace.events()]
        assert "SCRUB_PREVIEW_ENTER" in names

        controller.update_position(0.4, source="scrub")
        controller._scrub_cache.clear()
        controller._request_scrub_preview_decode(priority=True)
        assert any(e["event"] == "SCRUB_PREVIEW_REQUEST" for e in sm_trace.events())

        controller._scrubbing = False
        controller._scrub_preview_timer.stop()
        controller._set_pipeline_state(VideoPipelineState.FINAL_LANDING)
        controller._final_land_pending = True
        controller._release_target_song_time = 0.4
        controller._release_target_media_time = 0.4
        controller._final_land_transaction_id = controller._scrub_transaction_id
        controller._pre_scrub_was_playing = True
        controller._complete_final_land(0.4, np.full((8, 8, 3), 1, dtype=np.uint8))
        names = [e["event"] for e in sm_trace.events()]
        assert "FINAL_LAND_PRESENT" in names
        assert "RESUME_BEGIN" in names

    with patch.object(controller, "_decode_frame_array", side_effect=_fast):
        controller._request_async_live_frame(
            0.4, kind="play", force=True, scheduler="enter_resume_playback"
        )
        assert any(
            e["event"] == "SCHEDULE_NEXT_PLAY"
            and e.get("scheduler") == "enter_resume_playback"
            for e in sm_trace.events()
        )
        sm_trace.mark_land_present()
        controller._pipeline_state = VideoPipelineState.RESUME_PLAYBACK
        controller._resume_pending = True
        gen = controller._async_req_gen
        controller._on_async_frame_ready(
            gen, 0.41, np.full((8, 8, 3), 9, dtype=np.uint8), "play", "", -1
        )
        names = [e["event"] for e in sm_trace.events()]
        assert "FIRST_PLAY_FRAME" in names or "PLAY_PRESENT" in names

    report = sm_trace.report_text()
    assert "VIDEO_SM" in report
    controller.shutdown()
    perf_diag.set_enabled(False)


def test_sm_trace_records_pending_latest_while_worker_busy(
    app: QApplication, red_clip_path: Path
) -> None:
    """Round 8: busy play + new target → pending_latest_only (no gen bump)."""
    song = Song.create("Song")
    song.add_video_clip(_clip(red_clip_path))
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    sm_trace.clear()
    sm_trace.mark_land_present()
    controller._pipeline_state = VideoPipelineState.RESUME_PLAYBACK
    controller._playing = True
    controller._async_inflight = True
    controller._async_req_kind = "play"
    controller._async_req_seconds = 0.2
    gen_before = int(controller._async_req_gen)
    controller._schedule_playback_target(0.5, scheduler="enter_resume_playback")
    hits = [
        e
        for e in sm_trace.events()
        if e.get("event") == "SCHEDULE_NEXT_PLAY"
        and e.get("reason") == "pending_latest_only"
    ]
    assert hits
    assert hits[-1].get("scheduler") == "enter_resume_playback"
    assert int(controller._async_req_gen) == gen_before
    assert controller._play_pending_seconds == pytest.approx(0.5)
    controller._async_inflight = False
    controller.shutdown()
    perf_diag.set_enabled(False)


def test_sm_trace_included_in_perf_report() -> None:
    perf_diag.set_enabled(True)
    perf_diag.clear()
    sm_trace.trace(
        "RESUME_BEGIN",
        state="RESUME_PLAYBACK",
        generation=3,
        song_time=1.25,
        request_id=9,
        scheduler="enter_resume_playback",
    )
    text = perf_diag.report_text()
    assert "VIDEO_SM" in text
    assert "RESUME_BEGIN" in text
    perf_diag.set_enabled(False)


def test_worker_runtime_states_and_request_id() -> None:
    perf_diag.set_enabled(True)
    sm_trace.clear()
    assert sm_trace.worker_runtime() == sm_trace.WorkerRuntime.IDLE
    rid = sm_trace.next_request_id()
    sm_trace.set_worker_runtime(
        sm_trace.WorkerRuntime.SEEKING,
        request_id=rid,
        reason="test_seek",
        pipeline_state="RESUME_PLAYBACK",
    )
    assert sm_trace.worker_runtime() == sm_trace.WorkerRuntime.SEEKING
    snap = sm_trace.worker_snapshot()
    assert snap["current_request_id"] == rid
    assert snap["worker_runtime_request_id"] == rid
    sm_trace.set_worker_runtime(sm_trace.WorkerRuntime.DECODING, request_id=rid)
    sm_trace.set_worker_runtime(sm_trace.WorkerRuntime.WAITING_FRAME, request_id=rid)
    sm_trace.set_worker_runtime(sm_trace.WorkerRuntime.PRESENTING, request_id=rid)
    sm_trace.set_worker_runtime(sm_trace.WorkerRuntime.IDLE, request_id=rid)
    runtimes = [
        e.get("worker_runtime")
        for e in sm_trace.events()
        if e.get("event") == "WORKER_RUNTIME"
    ]
    assert sm_trace.WorkerRuntime.SEEKING in runtimes
    assert sm_trace.WorkerRuntime.DECODING in runtimes
    assert sm_trace.WorkerRuntime.IDLE in runtimes
    # Every event carries worker_runtime + request id fields.
    for e in sm_trace.events():
        assert "worker_runtime" in e
        assert e.get("request_id") is not None or e.get("current_request_id") is not None
    text = sm_trace.report_text()
    assert "worker_runtime=" in text
    assert "live worker_runtime=IDLE" in text
    perf_diag.set_enabled(False)


def test_classify_does_not_assume_worker_busy_without_evidence() -> None:
    perf_diag.set_enabled(True)
    sm_trace.clear()
    sm_trace.trace("FINAL_LAND_PRESENT", state="FINAL_LANDING", request_id=1)
    sm_trace.trace("RESUME_BEGIN", state="RESUME_PLAYBACK", request_id=1)
    sm_trace.set_worker_runtime(sm_trace.WorkerRuntime.IDLE, request_id=1)
    cls = sm_trace.classify_post_land_gap()
    # No schedules + idle → B or unknown; must NOT force A.
    assert cls["hypothesis"] != "A_worker_occupied"
    perf_diag.set_enabled(False)
