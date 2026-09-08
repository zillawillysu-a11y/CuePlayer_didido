"""Scrub mouse-up vs mouse-down static Timeline pixel parity."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Mark, Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _song_with_notes(n: int = 40) -> Song:
    song = Song.create("註解對齊測試")
    lane = song.mark_lanes[0]
    lane.visible = True
    lane.show_note_on_wave = True
    marks = [
        Mark.create(
            lane_index=lane.index,
            time_seconds=i * 0.25,
            display_name=f"標記{i}",
        )
        for i in range(n)
    ]
    song.marks = marks
    song.sort_marks()
    song.duration_seconds = 30.0
    return song


def _render_timeline(tl: TimelineWidget) -> QImage:
    img = QImage(tl.size(), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.black)
    tl.render(img)
    return img


def _mask_playhead_column(img: QImage, tl: TimelineWidget, pad: int = 10) -> QImage:
    """Copy image with the dynamic playhead column cleared."""
    out = img.copy()
    ph_x = int(round(tl._x_for_time(tl._position)))  # noqa: SLF001
    for x in range(max(0, ph_x - pad), min(out.width(), ph_x + pad + 1)):
        for y in range(out.height()):
            out.setPixel(x, y, 0)
    return out


def test_scrub_mousedown_static_pixels_match_mouseup(app: QApplication) -> None:
    """Static waveform/Marks/text must be pixel-identical while LMB is held."""
    tl = TimelineWidget()
    tl.resize(900, 420)
    tl.show()
    app.processEvents()
    song = _song_with_notes(50)
    tl.set_song(song)
    tl.set_position(5.0)
    tl._rebuild_scrub_backdrop(reason="parity_seed")  # noqa: SLF001
    app.processEvents()

    up = _mask_playhead_column(_render_timeline(tl), tl)

    # Simulate left-button scrub without invalidating the retained cache.
    tl._scrubbing = True  # noqa: SLF001
    tl._view_pinned = True  # noqa: SLF001
    tl.set_position(5.0)
    app.processEvents()
    down = _mask_playhead_column(_render_timeline(tl), tl)

    tl._scrubbing = False  # noqa: SLF001
    app.processEvents()
    up2 = _mask_playhead_column(_render_timeline(tl), tl)

    assert up.size() == down.size() == up2.size()
    # Retained native cache path: scrub-down matches scrub-up static pixels.
    assert up == down
    assert up == up2


def test_scrub_release_keeps_backdrop_for_first_wheel(app: QApplication) -> None:
    tl = TimelineWidget()
    tl.resize(800, 400)
    tl.show()
    app.processEvents()
    tl.set_song(_song_with_notes(20))
    tl._rebuild_scrub_backdrop(reason="seed")  # noqa: SLF001
    assert tl._scrub_backdrop is not None  # noqa: SLF001
    assert tl._spatial_backdrop is not None  # noqa: SLF001

    # Scrub press/release must not drop caches.
    tl._scrubbing = True  # noqa: SLF001
    tl._view_pinned = True  # noqa: SLF001
    if tl._scrub_backdrop is None:  # noqa: SLF001
        tl._rebuild_scrub_backdrop(reason="scrub_seed")  # noqa: SLF001
    held = tl._scrub_backdrop  # noqa: SLF001
    tl._scrubbing = False  # noqa: SLF001
    # Mimic release: end scrub only (no invalidate).
    assert tl._scrub_backdrop is held  # noqa: SLF001
    assert tl._spatial_backdrop is not None  # noqa: SLF001

    # First wheel zoom must seed from retained cache (no blank flash path).
    tl._begin_view_transform_gesture()  # noqa: SLF001
    assert tl._spatial_backdrop is not None  # noqa: SLF001
    assert tl._view_transform_busy is True  # noqa: SLF001
    tl._cancel_view_transform_gesture(rebuild=False, reason="test")  # noqa: SLF001


def test_zoom_note_layout_matches_static_bake(app: QApplication) -> None:
    """Zoom sprites place Notes under the ruler (canonical), not beside lane glyphs."""
    tl = TimelineWidget()
    tl.resize(800, 400)
    tl.show()
    app.processEvents()
    song = _song_with_notes(10)
    tl.set_song(song)
    tl._rebuild_scrub_backdrop(reason="layout")  # noqa: SLF001
    sprites = tl._mark_annotation_sprites  # noqa: SLF001
    assert sprites
    for sp in sprites:
        assert "wave_lines" in sp
        assert "lane_pixmap" in sp
        assert "lane_y" in sp
        # Notes belong in wave_lines; lane pixmap is glyph-only.
        if sp["wave_lines"]:
            assert any("標記" in line for line in sp["wave_lines"])
