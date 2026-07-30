"""Bottom transport: A/B right of Stop; overview ends above Clear (X)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.ui.transport_bar import BottomTransportBar


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_ab_is_right_of_stop_and_overview_ends_at_clear(app: QApplication) -> None:
    bar = BottomTransportBar()
    bar.resize(1200, 120)
    bar.show()
    app.processEvents()
    bar._sync_overview_width_to_clear()
    app.processEvents()

    play_l = bar.play_button.mapTo(bar, bar.play_button.rect().topLeft()).x()
    stop_r = bar.stop_button.mapTo(bar, bar.stop_button.rect().topRight()).x()
    a_l = bar.loop_a_button.mapTo(bar, bar.loop_a_button.rect().topLeft()).x()
    clear_r = bar.loop_clear_button.mapTo(bar, bar.loop_clear_button.rect().topRight()).x()
    overview_l = bar.overview.mapTo(bar, bar.overview.rect().topLeft()).x()
    overview_r = bar.overview.mapTo(bar, bar.overview.rect().topRight()).x()
    label_l = bar.loop_label.mapTo(bar, bar.loop_label.rect().topLeft()).x()

    assert a_l > stop_r
    assert label_l > clear_r
    # Overview spans Play…X (right edge above Clear).
    assert abs(overview_l - play_l) <= 4
    assert abs(overview_r - clear_r) <= 4
