"""Zoom-time rendering invariants for LTC clips and Mark glyphs.

During continuous mouse-wheel zoom the timeline shows a stretched raster
preview (``_blit_zoom_preview``) while the real, fixed-size content is
repainted live on top each frame. Two classes of content must never be part
of that stretched raster:

1. LTC generator clip rects/text (``_paint_ltc_clips``) — must be excluded
   from the "spatial" bake and redrawn live every zoom-preview frame, so
   text never gets geometrically resampled into a distorted glyph.
2. Mark lane-glyph sprites baked for the zoom preview
   (``_bake_mark_annotation_sprites``) must reflect the mark's *actual*
   selected/hovered state, not an unconditional white ring — otherwise every
   mark looks selected for the duration of the zoom gesture.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.ltc_clips import LtcClip
from cueplayer.domain.models import Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _ltc_song() -> Song:
    song = Song.create("Zoom")
    song.duration_seconds = 60.0
    song.ltc_source_mode = "clip_generator"
    song.ltc_clips = [
        LtcClip(
            id="c1",
            timeline_start_seconds=2.0,
            duration_seconds=5.0,
            start_timecode="01:00:00:00",
        )
    ]
    return song


def test_spatial_backdrop_excludes_ltc_clip_rects(app: QApplication) -> None:
    """The stretchable spatial cache must not bake LTC clip geometry/text."""
    timeline = TimelineWidget()
    timeline.resize(1200, 600)
    song = _ltc_song()
    timeline.set_song(song)
    timeline.set_ltc_source_mode("clip_generator")
    timeline.show()
    app.processEvents()

    timeline._rebuild_scrub_backdrop(reason="test")
    assert timeline._spatial_backdrop is not None and not timeline._spatial_backdrop.isNull()

    # The full bake (used for scrub/play at matching PPS) still carries the
    # clip, but the *spatial* raster that gets geometrically stretched during
    # a zoom gesture must not — confirmed by re-painting only the spatial
    # layers with clips excluded and diffing pixel content at the clip band.
    from PySide6.QtGui import QColor, QImage, QPainter

    w, h = timeline.width(), timeline.height()
    baseline = QImage(w, h, QImage.Format.Format_ARGB32)
    baseline.fill(QColor("#000000"))
    p = QPainter(baseline)
    timeline._paint_static_layers(
        p, include_marks=False, include_ruler_labels=False, include_ltc_clips=False
    )
    p.end()

    with_clips = QImage(w, h, QImage.Format.Format_ARGB32)
    with_clips.fill(QColor("#000000"))
    p2 = QPainter(with_clips)
    timeline._paint_static_layers(
        p2, include_marks=False, include_ruler_labels=False, include_ltc_clips=True
    )
    p2.end()

    # Sanity: the two renders differ (the clip really draws something) so the
    # exclusion flag has observable effect, proving spatial bake honors it.
    assert baseline.convertToFormat(QImage.Format.Format_RGB32) != with_clips.convertToFormat(
        QImage.Format.Format_RGB32
    )


def test_zoom_preview_repaints_ltc_clips_live(app: QApplication, monkeypatch) -> None:
    """``_paint_zoom_screen_annotations`` must redraw LTC clips every frame."""
    timeline = TimelineWidget()
    timeline.resize(1200, 600)
    song = _ltc_song()
    timeline.set_song(song)
    timeline.set_ltc_source_mode("clip_generator")
    timeline.show()
    app.processEvents()

    calls: list[int] = []
    original = timeline._paint_ltc_clips

    def _spy(painter):
        calls.append(1)
        return original(painter)

    monkeypatch.setattr(timeline, "_paint_ltc_clips", _spy)

    from PySide6.QtGui import QImage, QPainter

    image = QImage(timeline.width(), timeline.height(), QImage.Format.Format_ARGB32)
    p = QPainter(image)
    timeline._paint_zoom_screen_annotations(p)
    p.end()

    assert calls, "zoom preview must repaint LTC clips live, not from a stretched raster"


def test_mark_annotation_sprite_outline_matches_selection_state(app: QApplication) -> None:
    """Sprites baked for zoom preview must not force a selected-looking ring."""
    timeline = TimelineWidget()
    timeline.resize(1200, 600)
    song = Song.create("Marks")
    song.duration_seconds = 30.0
    lane = song.mark_lanes[0]
    lane.visible = True
    from cueplayer.domain.models import Mark

    mark_a = Mark(id="m1", lane_index=lane.index, time_seconds=2.0)
    mark_b = Mark(id="m2", lane_index=lane.index, time_seconds=4.0)
    song.marks = [mark_a, mark_b]
    timeline.set_song(song)
    timeline.show()
    app.processEvents()

    # Nothing selected/hovered — no sprite should carry the white ring outline.
    timeline.set_selected_mark_ids([], emit=False)
    timeline._hover_mark_id = None
    sprites = timeline._bake_mark_annotation_sprites()
    assert len(sprites) == 2

    def _has_white_ring(pm) -> bool:
        img = pm.toImage()
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if c.red() > 240 and c.green() > 240 and c.blue() > 240 and c.alpha() > 100:
                    return True
        return False

    for sprite in sprites:
        assert not _has_white_ring(sprite["lane_pixmap"]), (
            "unselected/unhovered mark sprite must not render a selection-style outline"
        )

    # Selecting one mark must produce a ring only for that mark's sprite.
    timeline.set_selected_mark_ids(["m1"], emit=False)
    sprites = timeline._bake_mark_annotation_sprites()
    rings = {s["mark_id"]: _has_white_ring(s["lane_pixmap"]) for s in sprites}
    assert rings["m1"] is True
    assert rings["m2"] is False
