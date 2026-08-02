"""Dialog prompting the user to install NDI Tools / Runtime or cyndilib."""

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

from cueplayer.playback.ndi_output import (
    NDI_RUNTIME_URL,
    NDI_TOOLS_URL,
    NdiFailureKind,
    ndi_failure_kind,
)


class NdiInstallDialog(QDialog):
    """Explain NDI setup failure; offer download links and/or pip guidance."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        detail: str = "",
        kind: NdiFailureKind | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("NDI Video Output")
        self.setModal(True)
        self.setMinimumWidth(460)

        resolved = kind or ndi_failure_kind(detail)
        root = QVBoxLayout(self)
        root.setSpacing(12)

        if resolved == "missing_package":
            title_text = "CuePlayer needs the cyndilib package"
            body_text = (
                "NDI Tools / Runtime on this PC is not enough by itself when you "
                "run CuePlayer from Python (dev / source).\n\n"
                "Install the Python NDI library, keep NDI Tools installed, then "
                "restart CuePlayer and turn NDI Output on again.\n\n"
                "In the same Python env you use to launch CuePlayer:\n"
                "  py -m pip install \"cyndilib>=0.0.7\"\n"
                "Or from the repo folder:\n"
                "  py -m pip install -e \".[ndi]\"\n\n"
                "If you use CuePlayer.exe instead, install a full employee build "
                "(packaged with NDI) — do not expect pip inside the .exe."
            )
        else:
            title_text = "NDI Tools / Runtime is required"
            body_text = (
                "CuePlayer’s NDI Output needs NDI installed on this PC.\n"
                "If you have not installed NDI Tools (or NDI Runtime), download it below, "
                "install it, then fully quit and restart CuePlayer (so PATH picks up "
                "the Runtime DLL) and turn NDI Output on again."
            )

        title = QLabel(title_text)
        title.setObjectName("ndiInstallTitle")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        root.addWidget(title)

        body = QLabel(body_text)
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
    kind: NdiFailureKind | None = None,
) -> None:
    """Show the NDI install dialog (modal)."""
    NdiInstallDialog(parent, detail=detail, kind=kind).exec()
