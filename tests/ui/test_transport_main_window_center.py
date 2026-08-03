"""Transport should center under the timeline column in the real main window."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_main_window_transport_centered_under_timeline(app: QApplication) -> None:
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    app.processEvents()
    window._sync_transport_layout()
    app.processEvents()

    transport = window.transport
    timeline = window.timeline
    play_l = transport.play_button.mapTo(transport, transport.play_button.rect().topLeft()).x()
    clear_r = transport.loop_clear_button.mapTo(
        transport, transport.loop_clear_button.rect().topRight()
    ).x()
    transport_c = (play_l + clear_r) / 2.0
    anchor_pt = timeline.transport_anchor_global_point()
    assert anchor_pt is not None
    timeline_c = transport.mapFromGlobal(anchor_pt).x()

    assert abs(transport_c - timeline_c) < 28
    # Transport no longer spans under the setlist column.
    assert transport.mapToGlobal(transport.rect().topLeft()).x() > window._setlist_panel.width() - 8
