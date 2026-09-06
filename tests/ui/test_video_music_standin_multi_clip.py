"""Music-lane video-audio stand-in must cover every Video Clip's own span.

Regression for: a Song with 2+ Video Clips and no music audio track only
ever showed the Music-lane stand-in waveform over the FIRST clip's region;
later clips' regions painted blank because ``TimelineWidget`` held a single
mutable ``_artifact_wave``/``_artifact_wave_clip`` pair mapped across the
whole lane, instead of one entry per clip.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.media.video_waveform_artifact import VideoWaveformArtifact
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _art(*, n: int = 200, dur: float = 10.0) -> VideoWaveformArtifact:
    return VideoWaveformArtifact(
        path="unused.mp4",
        mtime_ns=1,
        size=1,
        stream_index=0,
        format_version=1,
        peaks_per_second=float(n) / dur,
        origin_seconds=0.0,
        duration_seconds=dur,
        sample_rate=48000,
        channels=2,
        mins=np.full(n, -0.7, dtype=np.float32),
        maxs=np.full(n, 0.7, dtype=np.float32),
        coverage=np.ones(n, dtype=np.uint8),
        complete=True,
    )


def _has_wave_pixels(img: QImage, x0: int, x1: int, y0: int, y1: int) -> bool:
    """Scan the whole wave band — the envelope sits near the top/bottom edges
    at high amplitude, not necessarily at the vertical midpoint."""
    bg = QColor("#09090b").rgb()
    border = QColor("#27272a")
    for x in range(x0, x1):
        for y in range(y0, y1):
            if img.pixel(x, y) != bg and img.pixelColor(x, y) != border:
                return True
    return False


def _setup_timeline(tmp_path: Path, n_clips: int) -> tuple[TimelineWidget, Song, list[VideoClip]]:
    song = Song.create("MultiVid")
    clips: list[VideoClip] = []
    for i in range(n_clips):
        media = tmp_path / f"clip_{i}.mp4"
        media.write_bytes(f"fake{i}".encode())
        clip = VideoClip.create(
            path=media,
            name=f"Clip{i}",
            start_seconds=float(i * 4),
            duration_seconds=3.0,
            media_kind="video",
        )
        song.video_clips.append(clip)
        clips.append(clip)
    song.duration_seconds = float(n_clips * 4)
    tl = TimelineWidget()
    tl.resize(900, 300)
    tl._pixels_per_second = 40.0  # noqa: SLF001
    tl._scroll_x = 0.0  # noqa: SLF001
    tl.set_song(song)
    return tl, song, clips


def _render_music_lane(tl: TimelineWidget) -> QImage:
    image = QImage(900, 300, QImage.Format.Format_ARGB32)
    image.fill(QColor("#09090b"))
    painter = QPainter(image)
    tl._paint_waveform(painter)  # noqa: SLF001
    painter.end()
    return image


def test_two_clips_each_get_their_own_standin_span(app: QApplication, tmp_path: Path) -> None:
    del app
    tl, song, (clip_a, clip_b) = _setup_timeline(tmp_path, 2)

    tl.set_artifact_waveform_for_clip(clip_a, _art(), complete=True)
    tl.set_artifact_waveform_for_clip(clip_b, _art(), complete=True)

    img = _render_music_lane(tl)
    y0w = int(tl._ruler_height) + 2  # noqa: SLF001
    y1w = int(tl._ruler_height + tl._wave_height) - 2  # noqa: SLF001

    x0a = int(tl._x_for_time(clip_a.start_seconds)) + 2  # noqa: SLF001
    x1a = int(tl._x_for_time(clip_a.end_seconds)) - 2  # noqa: SLF001
    x0b = int(tl._x_for_time(clip_b.start_seconds)) + 2  # noqa: SLF001
    x1b = int(tl._x_for_time(clip_b.end_seconds)) - 2  # noqa: SLF001

    assert _has_wave_pixels(img, x0a, x1a, y0w, y1w), "clip A span must show its own waveform"
    assert _has_wave_pixels(img, x0b, x1b, y0w, y1w), (
        "clip B span must show its own waveform (this failed before the fix: "
        "only clip A's region painted)"
    )


def test_three_clips_not_only_first_has_standin(app: QApplication, tmp_path: Path) -> None:
    del app
    tl, song, clips = _setup_timeline(tmp_path, 3)
    for clip in clips:
        tl.set_artifact_waveform_for_clip(clip, _art(), complete=True)

    img = _render_music_lane(tl)
    y0w = int(tl._ruler_height) + 2  # noqa: SLF001
    y1w = int(tl._ruler_height + tl._wave_height) - 2  # noqa: SLF001

    for i, clip in enumerate(clips):
        x0 = int(tl._x_for_time(clip.start_seconds)) + 2  # noqa: SLF001
        x1 = int(tl._x_for_time(clip.end_seconds)) - 2  # noqa: SLF001
        assert _has_wave_pixels(img, x0, x1, y0w, y1w), f"clip index {i} has no stand-in waveform"


def test_deleting_first_clip_keeps_second_clip_standin(app: QApplication, tmp_path: Path) -> None:
    del app
    tl, song, (clip_a, clip_b) = _setup_timeline(tmp_path, 2)
    tl.set_artifact_waveform_for_clip(clip_a, _art(), complete=True)
    tl.set_artifact_waveform_for_clip(clip_b, _art(), complete=True)

    song.video_clips = [clip_b]
    tl.refresh_video_clip_waveforms()

    assert clip_a.id not in tl._artifact_waves  # noqa: SLF001
    assert clip_b.id in tl._artifact_waves  # noqa: SLF001

    img = _render_music_lane(tl)
    y0w = int(tl._ruler_height) + 2  # noqa: SLF001
    y1w = int(tl._ruler_height + tl._wave_height) - 2  # noqa: SLF001
    x0b = int(tl._x_for_time(clip_b.start_seconds)) + 2  # noqa: SLF001
    x1b = int(tl._x_for_time(clip_b.end_seconds)) - 2  # noqa: SLF001
    assert _has_wave_pixels(img, x0b, x1b, y0w, y1w)


def test_song_switch_clears_all_clip_standins(app: QApplication, tmp_path: Path) -> None:
    del app
    tl, song_a, (clip_a, clip_b) = _setup_timeline(tmp_path, 2)
    tl.set_artifact_waveform_for_clip(clip_a, _art(), complete=True)
    tl.set_artifact_waveform_for_clip(clip_b, _art(), complete=True)
    assert len(tl._artifact_waves) == 2  # noqa: SLF001

    song_b = Song.create("Other")
    tl.set_song(song_b)
    assert tl._artifact_waves == {}  # noqa: SLF001
