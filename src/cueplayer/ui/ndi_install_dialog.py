"""Dialog prompting the user to install NDI Tools / Runtime."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cueplayer.playback.ndi_output import NDI_RUNTIME_URL, NDI_TOOLS_URL


class NdiInstallDialog(QDialog):
    """Explain that NDI Tools/Runtime is required; offer clickable download links."""

    def __init__(self, parent: QWidget | None = None, *, detail: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("NDI Video Output")
        self.setModal(True)
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        title = QLabel("NDI Tools / Runtime is required")
        title.setObjectName("ndiInstallTitle")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        root.addWidget(title)

        body = QLabel(
            "CuePlayer’s NDI Output needs NDI installed on this PC.\n"
            "If you have not installed NDI Tools (or NDI Runtime), download it below, "
            "install it, then restart CuePlayer and turn NDI Output on again."
        )
        body.setObjectName("ndiInstallBody")
        body.setWordWrap(True)
        body.setStyleSheet("color: #c8c8c8;")
        root.addWidget(body)

        if detail.strip():
            detail_label = QLabel(detail.strip())
            detail_label.setObjectName("ndiInstallDetail")
            detail_label.setWordWrap(True)
            detail_label.setStyleSheet("color: #8a8a8a; font-size: 12px;")
            root.addWidget(detail_label)

        links = QLabel(
            f'<a href="{NDI_TOOLS_URL}">Download NDI Tools (recommended)</a><br>'
            f'<a href="{NDI_RUNTIME_URL}">Download NDI Runtime only</a>'
        )
        links.setObjectName("ndiInstallLinks")
        links.setTextFormat(Qt.TextFormat.RichText)
        links.setOpenExternalLinks(True)
        links.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        links.setStyleSheet("font-size: 13px;")
        root.addWidget(links)

        btn_row = QHBoxLayout()
        tools_btn = QPushButton("Open NDI Tools download…")
        tools_btn.setObjectName("ndiOpenToolsBtn")
        tools_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(NDI_TOOLS_URL)))
        runtime_btn = QPushButton("Open NDI Runtime download…")
        runtime_btn.setObjectName("ndiOpenRuntimeBtn")
        runtime_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(NDI_RUNTIME_URL)))
        btn_row.addWidget(tools_btn)
        btn_row.addWidget(runtime_btn)
        root.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)


def show_ndi_install_dialog(
    parent: QWidget | None,
    *,
    detail: str = "",
) -> None:
    """Show the NDI install dialog (modal)."""
    NdiInstallDialog(parent, detail=detail).exec()
