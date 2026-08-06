"""PLAYING vs PAUSED/STOPPED static Timeline pixel parity."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Mark, Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _song_with_notes(n: int = 40) -> Song:
    song = Song.create("播放靜止對齊")
    lane = song.mark_lanes[0]
    lane.visible = True
    lane.show_note_on_wave = True
    song.marks = [
        Mark.create(
            lane_index=lane.index,
            time_seconds=i * 0.25,
            display_name=f"標記{i}",
        )
        for i in range(n)
    ]
    song.sort_marks()
    song.duration_seconds = 30.0
    return song


def _render(tl: TimelineWidget) -> QImage:
    img = QImage(tl.size(), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.black)
    tl.render(img)
    return img


def _mask_playhead(img: QImage, tl: TimelineWidget, pad: int = 12) -> QImage:
    out = img.copy()
    ph_x = int(round(tl._device_snap(tl._x_for_time(tl._position))))  # noqa: SLF001
    for x in range(max(0, ph_x - pad), min(out.width(), ph_x + pad + 1)):
        for y in range(out.height()):
            out.setPixel(x, y, 0)
    return out


def test_playing_and_paused_static_pixels_match(app: QApplication) -> None:
    tl = TimelineWidget()
    tl.resize(900, 420)
    tl.show()
    app.processEvents()
    tl.set_song(_song_with_notes(40))
    tl.set_auto_scroll(False)
    tl.set_position(5.0)
    tl._rebuild_scrub_backdrop(reason="parity")  # noqa: SLF001
    app.processEvents()
    # Freeze scroll so transport cannot recenter the viewport.
    scroll0 = float(tl._scroll_x)  # noqa: SLF001
    pps0 = float(tl._pixels_per_second)  # noqa: SLF001

    tl.set_playing(False)
    tl._scroll_x = scroll0  # noqa: SLF001
    app.processEvents()
    paused = _mask_playhead(_render(tl), tl)

    tl.set_playing(True)
    tl._scroll_x = scroll0  # noqa: SLF001
    tl._pixels_per_second = pps0  # noqa: SLF001
    app.processEvents()
    playing = _mask_playhead(_render(tl), tl)

    tl.set_playing(False)
    tl._scroll_x = scroll0  # noqa: SLF001
    app.processEvents()
    stopped = _mask_playhead(_render(tl), tl)

    assert paused.size() == playing.size() == stopped.size()
    # Diff diagnostic: count differing pixels outside playhead mask.
    if paused != playing:
        diff = 0
        for y in range(paused.height()):
            for x in range(paused.width()):
                if paused.pixel(x, y) != playing.pixel(x, y):
                    diff += 1
        assert diff == 0, f"static pixel mismatches={diff}"
    assert paused == stopped

    # After PLAYING → PAUSED → PLAYING, static pixels must not gain/lose
    # residual dots under the waveform (playhead-masked).
    tl.set_playing(True)
    tl._scroll_x = scroll0  # noqa: SLF001
    app.processEvents()
    again = _mask_playhead(_render(tl), tl)
    assert again == paused
    assert tl._scrub_backdrop is not None  # noqa: SLF001


def test_set_playing_does_not_drop_valid_cache(app: QApplication) -> None:
    tl = TimelineWidget()
    tl.resize(800, 400)
    tl.show()
    app.processEvents()
    tl.set_song(_song_with_notes(10))
    tl._rebuild_scrub_backdrop(reason="seed")  # noqa: SLF001
    held = tl._scrub_backdrop  # noqa: SLF001
    tl.set_playing(True)
    assert tl._scrub_backdrop is held  # noqa: SLF001
    tl.set_playing(False)
    assert tl._scrub_backdrop is held  # noqa: SLF001


def test_native_blit_used_when_not_zooming(app: QApplication) -> None:
    tl = TimelineWidget()
    tl.resize(800, 400)
    tl.show()
    app.processEvents()
    tl.set_song(_song_with_notes(5))
    tl._rebuild_scrub_backdrop(reason="seed")  # noqa: SLF001
    tl.set_playing(True)
    assert tl._can_use_static_backdrop() is True  # noqa: SLF001
    assert tl._view_transform_busy is False  # noqa: SLF001
