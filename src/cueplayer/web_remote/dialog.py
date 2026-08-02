"""Tools → Web Remote… settings dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cueplayer.ui.checkbox import TickCheckBox
from cueplayer.web_remote.bridge import lan_urls
from cueplayer.web_remote.prefs import DEFAULT_PORT, WebRemotePrefs


class WebRemoteDialog(QDialog):
    """Enable LAN control from Safari / iPad (control only — no audio yet)."""

    def __init__(
        self,
        prefs: WebRemotePrefs,
        *,
        running: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Web Remote")
        self.resize(460, 360)
        self._result = WebRemotePrefs(
            enabled=bool(prefs.enabled),
            port=prefs.normalized_port(),
            password=str(prefs.password or ""),
            bind_lan=bool(prefs.bind_lan),
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        blurb = QLabel(
            "Control CuePlayer from Safari on the same LAN (iPad / phone). "
            "Playback, setlist, and marks run on this PC — LTC stays here. "
            "Remote Listen / Preview use WebRTC (low latency) on the same Wi‑Fi."
        )
        blurb.setWordWrap(True)
        blurb.setObjectName("webRemoteBlurb")
        root.addWidget(blurb)

        form = QFormLayout()
        form.setSpacing(8)

        self.enabled = TickCheckBox("Enable Web Remote server")
        self.enabled.setChecked(self._result.enabled)
        form.addRow("", self.enabled)

        self.bind_lan = TickCheckBox("Listen on LAN (0.0.0.0)")
        self.bind_lan.setChecked(self._result.bind_lan)
        self.bind_lan.setToolTip(
            "Off = localhost only (127.0.0.1). On = reachable from iPad on Wi‑Fi."
        )
        form.addRow("", self.bind_lan)

        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(self._result.normalized_port())
        form.addRow("Port", self.port)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setText(self._result.password)
        self.password.setPlaceholderText("Optional — blank = no password")
        self.password.setClearButtonEnabled(True)
        form.addRow("Password", self.password)

        show_pw = TickCheckBox("Show password")
        show_pw.toggled.connect(
            lambda on: self.password.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        form.addRow("", show_pw)
        root.addLayout(form)

        self.url_label = QLabel()
        self.url_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.url_label.setWordWrap(True)
        root.addWidget(self.url_label)

        btn_row = QHBoxLayout()
        copy_btn = QPushButton("Copy LAN URL")
        copy_btn.clicked.connect(self._copy_url)
        btn_row.addWidget(copy_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        status = QLabel("Running" if running else "Stopped")
        status.setObjectName("webRemoteStatus")
        root.addWidget(status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.port.valueChanged.connect(self._refresh_urls)
        self.bind_lan.toggled.connect(self._refresh_urls)
        self._refresh_urls()

    def result_prefs(self) -> WebRemotePrefs:
        return self._result

    def _refresh_urls(self) -> None:
        port = int(self.port.value())
        if self.bind_lan.isChecked():
            lines = lan_urls(port)
            text = "Open on iPad Safari:\n" + "\n".join(lines)
        else:
            text = f"Local only:\nhttp://127.0.0.1:{port}/"
        self.url_label.setText(text)

    def _copy_url(self) -> None:
        port = int(self.port.value())
        urls = lan_urls(port) if self.bind_lan.isChecked() else [f"http://127.0.0.1:{port}/"]
        pick = urls[-1] if len(urls) > 1 else urls[0]
        QGuiApplication.clipboard().setText(pick)
        QMessageBox.information(self, "Web Remote", f"Copied:\n{pick}")

    def _accept(self) -> None:
        self._result = WebRemotePrefs(
            enabled=self.enabled.isChecked(),
            port=int(self.port.value()) or DEFAULT_PORT,
            password=self.password.text(),
            bind_lan=self.bind_lan.isChecked(),
        )
        if self._result.enabled and self._result.bind_lan and not self._result.password:
            reply = QMessageBox.question(
                self,
                "Web Remote",
                "No password — anyone on this Wi‑Fi can control playback.\n"
                "Continue without a password?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.accept()
