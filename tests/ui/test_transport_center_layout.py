"""Bottom transport: Play/Pause/Stop centered; A/B on a side rail."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.ui.transport_bar import BottomTransportBar


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_play_cluster_is_window_centered(app: QApplication) -> None:
    bar = BottomTransportBar()
    bar.resize(1200, 100)
    bar.show()
    app.processEvents()

    play_c = bar.play_button.mapTo(bar, bar.play_button.rect().center()).x()
    stop_c = bar.stop_button.mapTo(bar, bar.stop_button.rect().center()).x()
    cluster_c = (play_c + stop_c) / 2.0
    assert abs(cluster_c - bar.width() / 2.0) < 24

    # A/B live on the left rail — not packed into the centered play cluster.
    a_x = bar.loop_a_button.mapTo(bar, bar.loop_a_button.rect().center()).x()
    assert a_x < play_c - 40
    label_right = bar.loop_label.mapTo(bar, bar.loop_label.rect().topRight()).x()
    assert label_right < play_c
