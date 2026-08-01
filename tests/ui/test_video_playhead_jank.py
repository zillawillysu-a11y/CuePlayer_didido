"""Playhead stays smooth while Video Track work is throttled on the UI thread."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.media.video_clip_waveform import ClipWaveformPeaks
from cueplayer.playback import video_sync as video_sync_mod
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_play_decode_cap_leaves_headroom_for_timeline() -> None:
    assert video_sync_mod._MAX_PLAY_DECODE_HZ <= 20.0
    assert video_sync_mod._MAX_PLAY_DECODE_HZ >= 12.0


def test_view_changed_throttled_while_playing(app: QApplication) -> None:
    song = Song.create("Jank")
    widget = TimelineWidget()
    widget.set_song(song)
    widget.resize(800, 400)
    widget.set_playing(True)

    events: list[int] = []
    widget.view_changed.connect(lambda: events.append(1))

    # Simulate ~60 Hz playhead ticks without scroll follow movement.
    widget._auto_scroll = False
    for i in range(30):
        widget.set_position(i * 0.016)

    # Overview mirror stays ~15 Hz even without scroll.
    assert 1 <= len(events) <= 12


def test_play_repaint_throttled_even_when_scroll_follows(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auto-scroll used to bypass the paint throttle every tick → low FPS feel."""
    song = Song.create("Follow")
    widget = TimelineWidget()
    widget.set_song(song)
    widget.resize(800, 400)
    widget.set_playing(True)
    widget._auto_scroll = True
    widget._view_pinned = False
    widget._pixels_per_second = 200.0

    clock_ns = [0]

    def _fake_mono() -> int:
        clock_ns[0] += 16_000_000  # ~60 Hz engine ticks
        return clock_ns[0]

    monkeypatch.setattr("cueplayer.ui.timeline_widget.monotonic_ns", _fake_mono)

    paints = 0
    original_update = widget.update

    def _counting_update(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal paints
        paints += 1
        return original_update(*args, **kwargs)

    widget.update = _counting_update  # type: ignore[method-assign]
    for i in range(60):
        widget.set_position(i * 0.05)

    # 33 ms paint interval over 60 × 16 ms ticks → ~30 paints, not 60.
    assert 20 <= paints <= 35


def test_play_uses_coarse_video_wave_and_wider_overscan(
    app: QApplication, tmp_path: Path
) -> None:
    media = tmp_path / "clip.mov"
    media.write_bytes(b"fake")
    song = Song.create("Vid")
    clip = VideoClip.create(
        path=media,
        name="Clip",
        start_seconds=0.0,
        duration_seconds=4.0,
        media_kind="video",
    )
    song.video_clips.append(clip)

    widget = TimelineWidget()
    widget.set_song(song)
    widget.resize(640, 400)
    widget.set_show_video_track(True, emit=False)

    peaks = ClipWaveformPeaks(
        sample_rate=48000,
        mono_origin_seconds=0.0,
        mono=np.linspace(-0.5, 0.5, 48000, dtype=np.float32),
        peak_levels=[],
        mins=np.full(64, -0.4, dtype=np.float32),
        maxs=np.full(64, 0.4, dtype=np.float32),
    )
    key = widget._video_waveform_cache.key_for(clip)
    widget._video_waveform_cache._peaks[key] = peaks

    widget.set_playing(True)
    assert widget._playing is True

    # Wider overscan while playing → fewer mid-play rebuilds.
    widget._rebuild_scrub_backdrop()
    assert widget._scrub_backdrop_overscan >= int(widget._view_width() * 1.4)

    pm = QPixmap(200, 40)
    pm.fill()
    painter = QPainter(pm)
    widget._paint_video_clip_waveform(painter, clip, QRectF(10, 5, 180, 30))
    painter.end()


def test_play_paint_does_not_submit_waveform_workers(
    app: QApplication, tmp_path: Path
) -> None:
    media = tmp_path / "clip.mov"
    media.write_bytes(b"fake")
    song = Song.create("Vid")
    clip = VideoClip.create(
        path=media,
        name="Clip",
        start_seconds=0.0,
        duration_seconds=2.0,
        media_kind="video",
    )
    song.video_clips.append(clip)

    widget = TimelineWidget()
    widget.set_song(song)
    widget.set_show_video_track(True, emit=False)
    widget.set_playing(True)

    submitted: list[object] = []
    cache = widget._video_waveform_cache
    original_submit = cache._executor.submit

    def _capture_submit(fn, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        submitted.append(args)
        return original_submit(fn, *args, **kwargs)

    cache._executor.submit = _capture_submit  # type: ignore[method-assign]
    assert cache.peaks_for_paint(clip, allow_submit=False) is None
    assert submitted == []


def test_playhead_dirty_update_when_scroll_static(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With Auto Scroll off, play ticks must not full-repaint the Video Track."""
    song = Song.create("Dirty")
    widget = TimelineWidget()
    widget.set_song(song)
    widget.resize(800, 400)
    widget.set_playing(True)
    widget._auto_scroll = False
    widget._last_playhead_paint_x = 100

    clock_ns = [0]

    def _fake_mono() -> int:
        clock_ns[0] += 40_000_000
        return clock_ns[0]

    monkeypatch.setattr("cueplayer.ui.timeline_widget.monotonic_ns", _fake_mono)

    regions: list[object] = []
    original_update = widget.update

    def _track_update(*args, **kwargs):  # noqa: ANN002, ANN003
        regions.append(args[0] if args else "full")
        return original_update(*args, **kwargs)

    widget.update = _track_update  # type: ignore[method-assign]
    widget.set_position(1.0)
    assert regions
    assert any(isinstance(r, QRect) for r in regions)
