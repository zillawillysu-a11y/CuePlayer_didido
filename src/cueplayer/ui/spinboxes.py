"""Spin boxes that ignore mouse wheel (typing / arrow buttons only)."""

from __future__ import annotations

from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox


class NoWheelSpinBox(QSpinBox):
    """QSpinBox that does not change value on mouse wheel."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that does not change value on mouse wheel."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class NoWheelComboBox(QComboBox):
    """QComboBox that does not change selection on mouse wheel."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()
