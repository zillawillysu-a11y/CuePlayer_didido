"""Backward scrub must always reach Final Land — even if mouseRelease is lost."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import Song, VideoClip
from cueplayer.playback.video_sync import VideoPipelineState, VideoSyncController
from cueplayer.ui.timeline_widget import TimelineWidget


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


def test_fallback_release_finalizes_when_left_button_up(
    app: QApplication, red_clip_path: Path
) -> None:
    """Windows-shaped: backward seek while play decode queued; lost mouseRelease.

    Global LeftButton becomes released while Timeline still thinks scrubbing;
    scrub timer fallback must finalize once and leave SCRUB_PREVIEW.
    """
    song = Song.create("Song")
    song.duration_seconds = 1200.0
    song.add_video_clip(
        VideoClip.create(
            name="red",
            path=str(red_clip_path),
            start_seconds=0.0,
            duration_seconds=1200.0,
        )
    )
    timeline = TimelineWidget()
    timeline.set_song(song)
    timeline.resize(1600, 480)
    timeline.show()
    app.processEvents()
    # Fit so 947s / 1018s are on-canvas.
    timeline.fit_to_view()
    app.processEvents()

    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_video_output_active(True)
    controller._playing = True
    controller._last_position_seconds = 1018.6

    land_requests: list[tuple[float, str]] = []
    ended = {"n": 0}

    def _on_scrub_started() -> None:
        controller.set_scrubbing(True, was_playing=True)

    def _on_scrub_ended() -> None:
        ended["n"] += 1
        controller.set_scrubbing(False)

    def _on_scrub_target(seconds: float) -> None:
        controller.update_position(float(seconds), source="scrub")

    timeline.scrub_started.connect(_on_scrub_started)
    timeline.scrub_ended.connect(_on_scrub_ended)
    timeline.scrub_target_changed.connect(_on_scrub_target)
    timeline.scrub_preview_requested.connect(_on_scrub_target)

    perf_diag.set_enabled(True)
    perf_diag.clear()

    # Begin scrub near 1018, move target to ~947.8 (no mouseRelease).
    # Widen PPS so both times fall inside the widget width.
    timeline._pixels_per_second = 1.0
    timeline._scroll_x = 900.0
    timeline.set_position(1018.6)
    app.processEvents()
    timeline._scrubbing = True
    timeline._view_pinned = True
    timeline.scrub_started.emit()
    assert controller.pipeline_state() == VideoPipelineState.SCRUB_PREVIEW
    x_target = timeline._x_for_time(947.824318)
    timeline._scrub_at(x_target, force=True)
    assert abs(float(controller._scrub_target_seconds) - 947.824318) < 1.0

    with (
        patch.object(
            controller,
            "_request_async_live_frame",
            side_effect=lambda seconds, **kw: land_requests.append(
                (float(seconds), str(kw.get("kind") or ""))
            ),
        ),
        patch(
            "cueplayer.ui.timeline_widget.QApplication.mouseButtons",
            return_value=Qt.MouseButton.NoButton,
        ),
    ):
        assert timeline.is_scrubbing()
        timeline._scrub_tick()
        timeline._scrub_tick()

    assert ended["n"] == 1
    assert not timeline.is_scrubbing()
    assert controller.pipeline_state() != VideoPipelineState.SCRUB_PREVIEW
    assert any(kind == "land" for _, kind in land_requests)

    controller._resume_watchdog.stop()
    controller._async_inflight = False
    try:
        controller._async_pool.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass
    timeline.close()
    perf_diag.set_enabled(False)


def test_end_scrub_once_is_idempotent(app: QApplication) -> None:
    song = Song.create("Song")
    timeline = TimelineWidget()
    timeline.set_song(song)
    timeline.resize(800, 300)
    count = {"n": 0}
    timeline.scrub_ended.connect(lambda: count.__setitem__("n", count["n"] + 1))
    timeline._scrubbing = True
    timeline._scrub_timer.start()
    timeline._end_scrub_once(reason="mouse_release", x=400.0)
    timeline._end_scrub_once(reason="fallback_left_button_up", x=400.0)
    assert count["n"] == 1
    assert not timeline.is_scrubbing()
    timeline.close()
