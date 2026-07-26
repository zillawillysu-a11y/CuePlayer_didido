"""Video preview surface shared by the embedded Preview panel and the
standalone Clean Video Output window, so both always paint the exact same
decoded frame (per PRODUCT_SPEC: no second independent video player)."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QWidget

FitMode = str  # "fit" | "fill"


class VideoPreviewWidget(QWidget):
    def __init__(self, parent: QWidget | None = None, *, placeholder_text: str = "No clip — black") -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._fit_mode: FitMode = "fit"
        self._placeholder_text = placeholder_text
        self.setStyleSheet("background: black;")
        self.setMinimumSize(160, 90)

    def fit_mode(self) -> FitMode:
        return self._fit_mode

    def set_fit_mode(self, mode: str) -> None:
        self._fit_mode = "fill" if mode == "fill" else "fit"
        self.update()

    def set_frame(self, frame: np.ndarray | None) -> None:
        if frame is None:
            if self._image is not None:
                self._image = None
                self.update()
            return
        frame = np.ascontiguousarray(frame)
        height, width = frame.shape[0], frame.shape[1]
        image = QImage(frame.data, width, height, frame.strides[0], QImage.Format.Format_RGB888)
        self._image = image.copy()  # detach from the short-lived numpy buffer
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("black"))
        if self._image is None or self._image.isNull():
            if self._placeholder_text:
                painter.setPen(QColor("#52525b"))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder_text)
            return

        target = self.rect()
        img_w, img_h = self._image.width(), self._image.height()
        if img_w <= 0 or img_h <= 0 or target.width() <= 0 or target.height() <= 0:
            return
        scale_fit = min(target.width() / img_w, target.height() / img_h)
        scale_fill = max(target.width() / img_w, target.height() / img_h)
        scale = scale_fit if self._fit_mode == "fit" else scale_fill
        draw_w = img_w * scale
        draw_h = img_h * scale
        x = target.x() + (target.width() - draw_w) / 2.0
        y = target.y() + (target.height() - draw_h) / 2.0

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self._fit_mode == "fill":
            painter.setClipRect(target)
        painter.drawImage(QRectF(x, y, draw_w, draw_h), self._image)
