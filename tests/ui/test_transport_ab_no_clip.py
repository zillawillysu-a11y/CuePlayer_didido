"""Transport A/B/Loop must stay fully visible when the bar is narrow."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from cueplayer.ui.transport_bar import BottomTransportBar


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_bar(app: QApplication, width: int) -> BottomTransportBar:
    """Host with fixed width — bare resize() is ignored once sizeHint expands."""
    host = QWidget()
    host.setFixedWidth(width)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    bar = BottomTransportBar()
    lay.addWidget(bar)
    host.show()
    app.processEvents()
    bar.sync_geometry()
    app.processEvents()
    # Keep host alive for the duration of the test via bar attribute.
    bar._test_host = host  # noqa: SLF001
    return bar


def _assert_child_inside(bar: BottomTransportBar, child) -> None:
    left = child.mapTo(bar, child.rect().topLeft()).x()
    right = child.mapTo(bar, child.rect().topRight()).x()
    assert left >= -1, f"{child.objectName() or child} left={left}"
    assert right <= bar.width() + 1, f"{child} right={right} bar={bar.width()}"


def _assert_no_horizontal_overlap(left_w, right_w) -> None:
    a_left = left_w.mapTo(left_w.window(), left_w.rect().topLeft()).x()
    a_right = left_w.mapTo(left_w.window(), left_w.rect().topRight()).x()
    b_left = right_w.mapTo(right_w.window(), right_w.rect().topLeft()).x()
    b_right = right_w.mapTo(right_w.window(), right_w.rect().topRight()).x()
    # Allow 1px touch; reject real overlap.
    assert a_right <= b_left + 1, (
        f"overlap: {left_w} [{a_left}-{a_right}] vs {right_w} [{b_left}-{b_right}]"
    )


def test_ab_cluster_fits_when_transport_is_narrow(app: QApplication) -> None:
    bar = _make_bar(app, 520)

    assert bar.width() == 520
    assert bar._transport_density in ("compact", "minimal")
    for child in (
        bar.play_button,
        bar.pause_button,
        bar.stop_button,
        bar.loop_a_button,
        bar.loop_b_button,
        bar.loop_button,
        bar.loop_clear_button,
    ):
        assert child.isVisible()
        _assert_child_inside(bar, child)
    _assert_no_horizontal_overlap(bar.loop_a_button, bar.loop_b_button)
    _assert_no_horizontal_overlap(bar.loop_b_button, bar.loop_button)
    _assert_no_horizontal_overlap(bar.loop_button, bar.loop_clear_button)


def test_ab_cluster_uses_minimal_density_when_very_narrow(app: QApplication) -> None:
    bar = _make_bar(app, 400)

    assert bar.width() == 400
    assert bar._transport_density in ("compact", "minimal")
    assert bar.loop_a_button.width() <= 36
    _assert_child_inside(bar, bar.loop_button)
    _assert_child_inside(bar, bar.loop_clear_button)
    _assert_no_horizontal_overlap(bar.loop_a_button, bar.loop_b_button)
    _assert_no_horizontal_overlap(bar.loop_b_button, bar.loop_button)
    _assert_no_horizontal_overlap(bar.loop_button, bar.loop_clear_button)
    if bar.volume_slider.isVisible():
        _assert_no_horizontal_overlap(bar.loop_clear_button, bar.volume_slider)
    if bar.music_mute_button.isVisible():
        _assert_no_horizontal_overlap(bar.loop_clear_button, bar.music_mute_button)
    # Overview stays inside its host (end time not cropped off-widget).
    ov = bar.overview
    host = bar._overview_host
    assert ov.x() >= 0
    assert ov.x() + ov.width() <= host.width() + 1
