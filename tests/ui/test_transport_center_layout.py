"""Play/Pause/Stop centered; A/B right of Stop; overview track aligns to X."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QWidget

from cueplayer.ui.timeline_overview import TimelineOverviewBar
from cueplayer.ui.transport_bar import BottomTransportBar


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_play_centered_ab_right_track_to_clear(app: QApplication) -> None:
    bar = BottomTransportBar()
    bar.resize(1200, 120)
    bar.show()
    app.processEvents()
    bar.sync_geometry()
    app.processEvents()

    play_c = bar.play_button.mapTo(bar, bar.play_button.rect().center()).x()
    stop_c = bar.stop_button.mapTo(bar, bar.stop_button.rect().center()).x()
    transport_c = (play_c + stop_c) / 2.0
    assert abs(transport_c - bar.width() / 2.0) < 20

    stop_r = bar.stop_button.mapTo(bar, bar.stop_button.rect().topRight()).x()
    a_l = bar.loop_a_button.mapTo(bar, bar.loop_a_button.rect().topLeft()).x()
    assert a_l > stop_r

    gutter = TimelineOverviewBar._LABEL_GUTTER
    play_l = bar.play_button.mapTo(bar, bar.play_button.rect().topLeft()).x()
    clear_r = bar.loop_clear_button.mapTo(bar, bar.loop_clear_button.rect().topRight()).x()
    # Track (excluding time gutters) spans Play…Clear.
    track_l = bar.overview.mapTo(bar, bar.overview.rect().topLeft()).x() + gutter
    track_r = bar.overview.mapTo(bar, bar.overview.rect().topRight()).x() - gutter
    assert abs(track_l - play_l) <= 4
    assert abs(track_r - clear_r) <= 4


def test_transport_follows_center_anchor(app: QApplication) -> None:
    host = QWidget()
    host.resize(1200, 200)
    host.show()
    anchor = QWidget(host)
    anchor.setGeometry(200, 0, 700, 120)
    anchor.show()
    bar = BottomTransportBar(host)
    bar.setGeometry(0, 120, 1200, 80)
    bar.show()
    bar.set_center_anchor(anchor)
    app.processEvents()

    play_l = bar.play_button.mapTo(bar, bar.play_button.rect().topLeft()).x()
    clear_r = bar.loop_clear_button.mapTo(bar, bar.loop_clear_button.rect().topRight()).x()
    transport_c = (play_l + clear_r) / 2.0
    anchor_c = bar.mapFromGlobal(anchor.mapToGlobal(anchor.rect().center())).x()
    assert abs(transport_c - anchor_c) < 24
