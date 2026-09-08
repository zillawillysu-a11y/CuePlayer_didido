"""About dialog: shows canonical app name, version, and copyright."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from cueplayer.app_info import APP_NAME, APP_VERSION, COPYRIGHT
from cueplayer.util.runtime import app_icon_path

_LOGO_LOGICAL_SIZE = 48


class AboutDialog(QDialog):
    """Simple modal About box: app name, version, copyright, one Close button."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setModal(True)
        self.setFixedSize(360, 200)

        icon_path = app_icon_path()
        icon_label: QLabel | None = None
        if icon_path is not None:
            icon = QIcon(str(icon_path))
            dpr = self.devicePixelRatioF() or 1.0
            device_size = round(_LOGO_LOGICAL_SIZE * dpr)
            # QIcon.pixmap() lets Qt pick the best-matching layer from a
            # multi-resolution .ico (or rasterize an .svg) at the requested
            # device size, instead of upscaling a fixed small frame.
            pixmap = icon.pixmap(device_size, device_size)
            pixmap.setDevicePixelRatio(dpr)
            if not pixmap.isNull():
                icon_label = QLabel(self)
                icon_label.setFixedSize(_LOGO_LOGICAL_SIZE, _LOGO_LOGICAL_SIZE)
                icon_label.setPixmap(pixmap)
                self.setWindowIcon(icon)

        name_label = QLabel(APP_NAME, self)
        name_font = name_label.font()
        name_font.setPointSize(name_font.pointSize() + 4)
        name_font.setBold(True)
        name_label.setFont(name_font)

        version_label = QLabel(f"Version {APP_VERSION}", self)
        copyright_label = QLabel(COPYRIGHT, self)
        copyright_label.setWordWrap(True)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        text_layout.addWidget(name_label)
        text_layout.addWidget(version_label)
        text_layout.addStretch(1)
        text_layout.addWidget(copyright_label)

        header_layout = QHBoxLayout()
        if icon_label is not None:
            header_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        header_layout.addLayout(text_layout, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addLayout(header_layout)
        layout.addStretch(1)
        layout.addWidget(buttons)
