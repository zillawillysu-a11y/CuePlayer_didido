"""Optional LTC inspect waveform lane (show/hide eye)."""

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
    # Square-ish stripe stand-in
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


def test_show_ltc_track_persists(tmp_path: Path) -> None:
    project = Project.create("Show")
    project.songs[0].show_ltc_track = True
    project.songs[0].ltc_lane_height = 64.0
    path = tmp_path / "中文" / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.songs[0].show_ltc_track is True
    assert loaded.songs[0].ltc_lane_height == 64.0


def test_show_ltc_track_defaults_false_for_legacy(tmp_path: Path) -> None:
    project = Project.create("Legacy")
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)
    text = path.read_text(encoding="utf-8")
    assert '"show_ltc_track"' in text
    text = text.replace('"show_ltc_track": false,\n', "", 1)
    text = text.replace('"ltc_lane_height": 56.0,\n', "", 1)
    path.write_text(text, encoding="utf-8")
    loaded = load_project(path)
    assert loaded.songs[0].show_ltc_track is False


def test_ltc_waveform_include_channel() -> None:
    buf, ch = _stereo_buffer(ltc_on_right=True)
    music = waveform_display_buffer(buf, exclude_channel=ch)
    ltc = ltc_waveform_display_buffer(buf, ch)
    assert ltc is not None
    assert not np.allclose(music.mono, ltc.mono)
    assert float(np.max(np.abs(ltc.mono))) > 0.1


def test_hide_ltc_track_collapses_lane(app: QApplication) -> None:
    widget = TimelineWidget()
    song = Song.create("Stripe")
    song.show_ltc_track = True
    song.show_video_track = False
    widget.set_song(song)
    buf, ch = _stereo_buffer(ltc_on_right=False)
    widget.set_ltc_audio(ltc_waveform_display_buffer(buf, ch), channel=ch)
    widget.resize(900, 600)
    assert widget._ltc_lane_visible() is True
    before = widget._tracks_top_y()
    wave_bottom = widget._wave_bottom_y()
    assert before > wave_bottom

    events: list[bool] = []
    widget.ltc_track_visibility_changed.connect(events.append)
    widget.set_show_ltc_track(False)

    assert song.show_ltc_track is False
    assert widget._ltc_lane_visible() is False
    assert widget._ltc_eye_header_visible() is True
    assert widget._tracks_top_y() == wave_bottom
    assert events == [False]
    assert widget.ltc_show_button.isHidden() is False
    assert widget.ltc_hide_button.isHidden() is True


def test_show_eye_restores_ltc_track(app: QApplication) -> None:
    widget = TimelineWidget()
    song = Song.create("Stripe")
    song.show_ltc_track = False
    widget.set_song(song)
    buf, ch = _stereo_buffer()
    widget.set_ltc_audio(ltc_waveform_display_buffer(buf, ch), channel=ch)
    widget.resize(900, 600)
    assert widget.ltc_show_button.isHidden() is False
    widget.ltc_show_button.click()
    assert song.show_ltc_track is True
    assert widget._ltc_lane_visible() is True
    assert widget.ltc_hide_button.isHidden() is False
