"""Status-bar progress while warming waveforms / LTC after setlist import."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_media_warm_progress_counts_and_clears(app: QApplication) -> None:
    window = MainWindow(Project.create("Warm"))
    window.show()
    app.processEvents()

    key_a = ("/fake/a.wav", 1, 10)
    key_b = ("/fake/b.wav", 2, 20)
    window._media_warm_units = {
        key_a: {"audio": False, "ltc": False},
        key_b: {"audio": False, "ltc": False},
    }
    window._media_warm_active = True

    assert window._media_warm_counts() == (0, 4)
    window._refresh_media_warm_status()
    msg = window.status.currentMessage()
    assert "Loading waveform / LTC:" in msg
    assert "0%" in msg or "0/" in msg

    window._note_media_warm_step(key_a, "audio")
    window._note_media_warm_step(key_a, "ltc")
    window._note_media_warm_step(key_b, "audio")
    assert window._media_warm_counts() == (3, 4)
    window._refresh_media_warm_status()
    assert "75%" in window.status.currentMessage()

    window._note_media_warm_step(key_b, "ltc")
    window._refresh_media_warm_status()
    assert window._media_warm_active is False
    assert "ready" in window.status.currentMessage().lower()


def test_refresh_status_defers_to_media_warm(app: QApplication) -> None:
    window = MainWindow(Project.create("Warm"))
    window._media_warm_units = {("x", 1, 1): {"audio": True, "ltc": False}}
    window._media_warm_active = True
    window._refresh_status()
    assert "Loading waveform / LTC:" in window.status.currentMessage()
