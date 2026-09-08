"""LTC lane under Video; Marks under Video/LTC; one eye toggles Video + LTC."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project, Song
from cueplayer.media.audio_loader import AudioBuffer, ltc_waveform_display_buffer, waveform_display_buffer
from cueplayer.persistence.project_store import load_project, save_project
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stereo_buffer(*, ltc_on_right: bool = True) -> tuple[AudioBuffer, int]:
    sr = 48000
    n = sr * 2
    t = np.linspace(0.0, 2.0, n, endpoint=False)
    music = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    stripe = np.sign(np.sin(2 * np.pi * 1200 * t)).astype(np.float32) * 0.8
    if ltc_on_right:
        samples = np.stack([music, stripe], axis=1)
        ch = 1
    else:
        samples = np.stack([stripe, music], axis=1)
        ch = 0
    from cueplayer.media.audio_loader import build_peak_pyramid

    mono, levels = build_peak_pyramid(samples, sr)
    buf = AudioBuffer(
        path=Path("synth.wav"),
        sample_rate=sr,
        samples=samples,
        mono=mono,
        peak_levels=levels,
    )
    return buf, ch


def test_show_ltc_track_persists_with_height(tmp_path: Path) -> None:
    project = Project.create("Show")
    project.songs[0].show_ltc_track = True
    project.songs[0].ltc_lane_height = 64.0
    path = tmp_path / "中文" / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.songs[0].show_ltc_track is True
    assert loaded.songs[0].ltc_lane_height == 64.0


def test_ltc_waveform_include_channel() -> None:
    buf, ch = _stereo_buffer(ltc_on_right=True)
    music = waveform_display_buffer(buf, exclude_channel=ch)
    ltc = ltc_waveform_display_buffer(buf, ch)
    assert ltc is not None
    assert not np.allclose(music.mono, ltc.mono)
    assert float(np.max(np.abs(ltc.mono))) > 0.1


def test_ltc_sits_below_video(app: QApplication) -> None:
    widget = TimelineWidget()
    song = Song.create("Stripe")
    song.show_video_track = True
    widget.set_song(song)
    buf, ch = _stereo_buffer()
    widget.set_ltc_audio(ltc_waveform_display_buffer(buf, ch), channel=ch)
    widget.resize(900, 600)
    assert widget._ltc_lane_visible() is True
    # Music → Video → LTC → Marks
    assert widget._video_lane_top_y() == widget._wave_bottom_y()
    assert widget._ltc_lane_top_y() == widget._video_lane_top_y() + int(
        widget._video_lane_height
    )
    assert widget._tracks_top_y() == widget._ltc_lane_top_y() + widget._ltc_band_height()


def test_marks_sit_below_video_and_ltc(app: QApplication) -> None:
    """Video/LTC stay under Music; Marks are pushed below (scroll to reach)."""
    widget = TimelineWidget()
    song = Song.create("With Video")
    song.show_video_track = True
    widget.set_song(song)
    widget.set_show_video_track(True)
    widget.resize(900, 600)
    assert widget._video_lane_top_y() == widget._wave_bottom_y()
    assert widget._tracks_top_y() >= widget._video_lane_top_y() + int(
        widget._video_lane_height
    )
    marks_top = widget._tracks_top_y()
    assert widget._in_mark_tracks(widget._header_width + 10, marks_top + 4)
    assert not widget._in_mark_tracks(
        widget._header_width + 10, widget._video_lane_top_y() + 4
    )


def test_ltc_lane_uses_filled_silhouette_painters(app: QApplication) -> None:
    """LTC must not reuse stroke-per-pixel music painters (looks falsely hairy)."""
    widget = TimelineWidget()
    assert hasattr(widget, "_paint_ltc_silhouette_peaks")
    assert hasattr(widget, "_paint_ltc_silhouette_raw")


def test_video_eye_hides_ltc_together(app: QApplication) -> None:
    widget = TimelineWidget()
    song = Song.create("Stripe")
    widget.set_song(song)
    widget.set_show_video_track(True)
    buf, ch = _stereo_buffer(ltc_on_right=False)
    widget.set_ltc_audio(ltc_waveform_display_buffer(buf, ch), channel=ch)
    widget.resize(900, 600)
    assert widget._ltc_lane_visible() is True
    wave_bottom = widget._wave_bottom_y()

    events: list[bool] = []
    widget.video_track_visibility_changed.connect(events.append)
    widget.set_show_video_track(False)

    assert song.show_video_track is False
    assert song.show_ltc_track is False
    assert widget._ltc_lane_visible() is False
    assert widget._video_lane_visible() is False
    assert widget._tracks_top_y() == wave_bottom
    assert events == [False]
    assert widget.video_show_button.isHidden() is False
    assert not hasattr(widget, "ltc_show_button")


def test_video_eye_shows_ltc_together(app: QApplication) -> None:
    widget = TimelineWidget()
    song = Song.create("Stripe")
    widget.set_song(song)
    widget.set_show_video_track(False)
    buf, ch = _stereo_buffer()
    widget.set_ltc_audio(ltc_waveform_display_buffer(buf, ch), channel=ch)
    widget.resize(900, 600)
    assert widget._ltc_lane_visible() is False
    assert widget.video_show_button.isHidden() is False
    assert widget.video_show_button._kind == "eye"
    eye_pos = widget.video_show_button.pos()
    widget.video_show_button.click()
    assert song.show_video_track is True
    assert song.show_ltc_track is True
    assert widget._ltc_lane_visible() is True
    assert widget.video_show_button.isHidden() is False
    assert widget.video_show_button.pos() == eye_pos
    assert widget.video_show_button._kind == "eye_off"
    assert widget.video_hide_button.isHidden() is True
