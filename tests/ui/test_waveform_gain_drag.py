"""Waveform / LTC volume lines must stay aligned with the mouse after zoom."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _widget_with_gain_line(app: QApplication) -> tuple[TimelineWidget, Song]:
    widget = TimelineWidget()
    song = Song.create("Gain")
    song.duration_seconds = 120.0
    song.audio_gain_db = 0.0
    widget.resize(900, 520)
    widget.set_song(song)
    widget._audio_loading = True  # bounds available without decoding audio
    widget._show_wave_gain_line = True
    widget.show()
    app.processEvents()
    return widget, song


def test_scrub_backdrop_does_not_bake_gain_overlays(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stale baked gain lines drift under the live overlay after zoom/play."""
    widget, _song = _widget_with_gain_line(app)
    calls: list[int] = []
    original = TimelineWidget._paint_audio_gain_overlays

    def _track(self: TimelineWidget, painter) -> None:  # noqa: ANN001
        calls.append(1)
        original(self, painter)

    monkeypatch.setattr(TimelineWidget, "_paint_audio_gain_overlays", _track)
    widget._rebuild_scrub_backdrop()
    assert calls == []


def test_gain_drag_after_zoom_uses_press_time_bounds(app: QApplication) -> None:
    widget, song = _widget_with_gain_line(app)
    bounds = widget._wave_gain_bounds()
    assert bounds is not None
    top, bottom = bounds
    zero_y = widget._y_for_gain_db(0.0, top, bottom)

    widget.set_zoom(280.0)
    app.processEvents()

    widget._dragging_audio_gain = True
    widget._audio_gain_zone = "wave"
    widget._audio_gain_drag_bounds = bounds
    widget._apply_gain_at_y(zero_y, "wave")
    assert song.audio_gain_db == pytest.approx(0.0, abs=0.05)

    widget.set_wave_height(widget._wave_height + 40)
    app.processEvents()
    widget._apply_gain_at_y(zero_y, "wave")
    assert song.audio_gain_db == pytest.approx(0.0, abs=0.05)
