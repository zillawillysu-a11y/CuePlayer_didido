"""Main application window (MVP skeleton)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow, QStatusBar, QVBoxLayout, QWidget

from cueplayer.domain.models import Project


class MainWindow(QMainWindow):
    def __init__(self, project: Project | None = None) -> None:
        super().__init__()
        self.project = project or Project.create("未命名專案")
        self.setWindowTitle(f"CuePlayer — {self.project.name}")
        self.resize(1280, 720)

        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("CuePlayer")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        title.setStyleSheet("font-size: 28px; font-weight: 600;")

        subtitle = QLabel(
            "Milestone 1 skeleton\n"
            "下一步：Audio routing spike → MA golden XML → Timeline UI"
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 14px; color: #555;")

        project_info = QLabel(
            f"專案：{self.project.name}\n"
            f"歌曲數：{len(self.project.songs)}\n"
            f"Schema：v{self.project.schema_version}"
        )
        project_info.setStyleSheet("font-size: 13px;")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addWidget(project_info)
        layout.addStretch(1)
        self.setCentralWidget(root)

        status = QStatusBar(self)
        status.showMessage("Ready — Unicode / 中文路徑支援已納入 persistence 測試")
        self.setStatusBar(status)
