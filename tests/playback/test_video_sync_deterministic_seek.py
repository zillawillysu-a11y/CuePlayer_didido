"""Sprint 8 Task 2 Round 8 — deterministic seek, handoff, no-black first frame."""

from __future__ import annotations

import time
from pathlib import Path

import av
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import Song, VideoClip
from cueplayer.media.video_loader import SeekTelemetry, VideoDecoder
from cueplayer.playback.video_sync import (
    DisplaySource,
    PlaybackDecoderHandoff,
    VideoPipelineState,
    VideoSyncController,
)

WIDTH, HEIGHT, FPS = 32, 24, 10


def _make_solid_clip(path: Path, color: tuple[int, int, int], *, seconds: float = 4.0) -> None:
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
    _make_solid_clip(path, (255, 0, 0), seconds=4.0)
    return path


def _shutdown(controller: VideoSyncController) -> None:
    try:
        controller.shutdown()
    except Exception:
        pass


def _song(path: Path, *, duration: float = 4.0) -> Song:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=path, start_seconds=0.0, duration_seconds=duration
        )
    )
    return song


def test_inflight_play_survives_clock_advancement(
    app: QApplication, red_clip_path: Path
) -> None:
    controller = VideoSyncController()
    try:
        controller.set_song(_song(red_clip_path))
        controller.set_playing(True)
        controller._async_inflight = True
        controller._async_req_kind = "play"
        gen = int(controller._async_req_gen)
        for i in range(10):
            controller.update_position(0.5 + 0.03 * i, source="engine")
        assert int(controller._async_req_gen) == gen
        assert controller._play_pending_seconds is not None
    finally:
        controller._async_inflight = False
        _shutdown(controller)


def test_playback_decoder_handoff_after_playing_scrub_release(
    app: QApplication, red_clip_path: Path
) -> None:
    controller = VideoSyncController()
    try:
        controller.set_song(_song(red_clip_path))
        controller.set_scrubbing(True, was_playing=True)
        controller.update_position(0.8, source="scrub")
        controller._scrubbing = False
        controller._final_land_pending = False
        controller._release_target_song_time = 0.8
        controller._pre_scrub_was_playing = True
        controller._playing = True
        controller._enter_resume_playback()
        assert (
            controller._playback_handoff
            == PlaybackDecoderHandoff.PLAYBACK_DECODER_PREPARING
        )
        frame = np.full((8, 8, 3), 50, dtype=np.uint8)
        controller._on_async_frame_ready(
            controller._async_req_gen,
            0.8,
            frame,
            "play",
            "",
            controller._scrub_session_gen,
        )
        assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
        assert controller._display_source == DisplaySource.PLAYBACK_FRAME
    finally:
        controller._resume_watchdog.stop()
        controller._async_inflight = False
        _shutdown(controller)


def test_last_valid_kept_during_decoder_preparing(
    app: QApplication, red_clip_path: Path
) -> None:
    controller = VideoSyncController()
    try:
        controller.set_song(_song(red_clip_path))
        keep = np.full((8, 8, 3), 99, dtype=np.uint8)
        controller._emit_frame(keep, reason="seed")
        controller._last_valid_frame = keep
        controller._set_playback_handoff(
            PlaybackDecoderHandoff.PLAYBACK_DECODER_PREPARING
        )
        controller._emit_frame(None, allow_clear=False, reason="preparing")
        assert controller._last_emitted_frame is keep
        assert controller._display_source == DisplaySource.LAST_VALID
    finally:
        _shutdown(controller)


def test_no_empty_widget_when_video_exists_on_activate(
    app: QApplication, red_clip_path: Path
) -> None:
    controller = VideoSyncController()
    try:
        keep = np.full((8, 8, 3), 40, dtype=np.uint8)
        controller._emit_frame(keep, reason="seed")
        frames: list[object] = []
        controller.frame_changed.connect(frames.append)
        controller.set_song(_song(red_clip_path))
        assert None not in frames
        assert controller._display_source == DisplaySource.LAST_VALID
        assert controller._song_activate_mono is not None
    finally:
        _shutdown(controller)


def test_seek_backward_after_eof_recovers(red_clip_path: Path) -> None:
    decoder = VideoDecoder(red_clip_path)
    try:
        near_end = decoder.frame_at(3.8)
        assert near_end is not None
        early = decoder.frame_at(0.1)
        assert early is not None
        assert early.mean(axis=(0, 1))[0] > 200
        assert decoder.last_seek.requested_time == pytest.approx(0.1)
    finally:
        decoder.close()


def test_seek_records_keyframe_telemetry(red_clip_path: Path) -> None:
    decoder = VideoDecoder(red_clip_path)
    try:
        decoder.frame_at(2.5)
        tel = decoder.last_seek
        assert isinstance(tel, SeekTelemetry)
        assert tel.requested_time == pytest.approx(2.5)
        assert tel.frames_to_target >= 0
        assert tel.total_ms >= 0.0
        assert tel.time_base > 0.0
    finally:
        decoder.close()


def test_seek_deadline_flags_timeout(
    monkeypatch: pytest.MonkeyPatch, red_clip_path: Path
) -> None:
    import cueplayer.media.video_loader as vl

    monkeypatch.setattr(vl, "_SEEK_DECODE_DEADLINE_S", 0.0)
    monkeypatch.setattr(vl, "_MAX_FRAMES_TO_TARGET", 1)
    decoder = VideoDecoder(red_clip_path)
    try:
        decoder.frame_at(0.0)
        decoder.frame_at(3.5, deadline_s=0.0)
        assert decoder.last_seek.requested_time == pytest.approx(3.5)
    finally:
        decoder.close()


def test_same_state_sequence_across_timestamps(
    app: QApplication, red_clip_path: Path
) -> None:
    controller = VideoSyncController()
    try:
        controller.set_song(_song(red_clip_path))
        sequences: list[list[str]] = []
        for t in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
            if controller.is_scrubbing():
                controller._scrubbing = False
            controller.set_scrubbing(True, was_playing=True)
            states = [controller.pipeline_state()]
            controller.update_position(t, source="scrub")
            controller._release_target_song_time = float(t)
            controller._pre_scrub_was_playing = True
            controller._scrubbing = False
            controller._final_land_pending = False
            controller._enter_resume_playback()
            states.append(controller.pipeline_state())
            states.append(controller._playback_handoff)
            sequences.append(states)
            controller._resume_watchdog.stop()
            controller._invalidate_async_requests()
            controller._async_inflight = False
            controller._set_pipeline_state(VideoPipelineState.PLAYBACK)
            controller._set_playback_handoff(PlaybackDecoderHandoff.IDLE)
        for seq in sequences:
            assert seq[0] == VideoPipelineState.SCRUB_PREVIEW
            assert seq[1] == VideoPipelineState.RESUME_PLAYBACK
            assert seq[2] == PlaybackDecoderHandoff.PLAYBACK_DECODER_PREPARING
    finally:
        _shutdown(controller)


def test_twenty_random_seeks_no_stuck_state(
    app: QApplication, red_clip_path: Path
) -> None:
    rng = np.random.default_rng(42)
    controller = VideoSyncController()
    try:
        controller.set_song(_song(red_clip_path))
        controller.land_frame_at(0.2)
        app.processEvents()
        for _ in range(20):
            t = float(rng.uniform(0.05, 3.8))
            controller.set_playing(False)
            controller.update_position(t, source="engine")
            assert controller.pipeline_state() != VideoPipelineState.FINAL_LANDING
            assert controller._display_source != DisplaySource.EMPTY_WIDGET
        assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
    finally:
        _shutdown(controller)


def test_song_activate_requests_frame_without_play(
    app: QApplication, red_clip_path: Path
) -> None:
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller = VideoSyncController()
    try:
        controller.set_song(_song(red_clip_path))
        controller.land_frame_at(0.25)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            app.processEvents()
            if controller._is_valid_frame_array(controller._last_emitted_frame):
                break
            time.sleep(0.01)
        assert controller._is_valid_frame_array(controller._last_emitted_frame)
        assert controller._display_source != DisplaySource.EMPTY_WIDGET
    finally:
        perf_diag.set_enabled(False)
        _shutdown(controller)
