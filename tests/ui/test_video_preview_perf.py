"""VideoPreviewWidget: shared QImage path + Clean Output fast scale."""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.ui.video_output_window import CleanVideoOutputWindow
from cueplayer.ui.video_preview import VideoPreviewWidget, rgb_frame_to_qimage


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_rgb_frame_to_qimage_detaches(app: QApplication) -> None:
    frame = np.zeros((16, 24, 3), dtype=np.uint8)
    frame[:] = (10, 20, 30)
    image = rgb_frame_to_qimage(frame)
    assert image.width() == 24
    assert image.height() == 16
    frame[:] = 0
    # Detached copy must keep original pixels.
    assert image.pixelColor(0, 0).red() == 10


def test_set_qimage_shares_without_recopy(app: QApplication) -> None:
    widget = VideoPreviewWidget()
    widget.show()
    app.processEvents()
    frame = np.full((8, 12, 3), 40, dtype=np.uint8)
    image = rgb_frame_to_qimage(frame)
    widget.set_qimage(image)
    assert widget._image is image


def test_clean_output_uses_smooth_scale(app: QApplication) -> None:
    window = CleanVideoOutputWindow()
    assert window.preview._smooth_scale is True


def test_embedded_preview_defaults_to_fast_scale(app: QApplication) -> None:
    """Timeline-side Preview prefers nearest-neighbor so playhead paint wins
    over SmoothPixmapTransform on every video frame (Clean keeps smooth)."""
    widget = VideoPreviewWidget(smooth_scale=False)
    assert widget._smooth_scale is False
