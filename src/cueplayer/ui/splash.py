"""Dark startup splash — avoids a blank white window while CuePlayer loads."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from cueplayer.ui.theme import ACCENT, BG_APP, BORDER, TEXT, TEXT_MUTED


def create_splash_pixmap(
    *,
    width: int = 520,
    height: int = 300,
    message: str = "Loading…",
) -> QPixmap:
    """Paint a CuePlayer-branded dark splash (no external image assets)."""
    pixmap = QPixmap(max(320, width), max(200, height))
    pixmap.fill(QColor(BG_APP))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Soft outer frame
    painter.setPen(QColor(BORDER))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(pixmap.rect().adjusted(1, 1, -2, -2), 12, 12)

    # Accent bar under the brand
    bar_y = height // 2 + 8
    painter.fillRect(width // 2 - 36, bar_y, 72, 2, QColor(ACCENT))

    title_font = QFont()
    title_font.setFamilies(["Segoe UI", "Microsoft JhengHei UI", "Arial"])
    title_font.setPixelSize(34)
    title_font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(title_font)
    painter.setPen(QColor(TEXT))
    painter.drawText(
        pixmap.rect().adjusted(0, -28, 0, 0),
        int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
        "CuePlayer",
    )

    msg_font = QFont()
    msg_font.setFamilies(["Segoe UI", "Microsoft JhengHei UI", "Arial"])
    msg_font.setPixelSize(13)
    painter.setFont(msg_font)
    painter.setPen(QColor(TEXT_MUTED))
    painter.drawText(
        0,
        bar_y + 28,
        width,
        24,
        int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
        message,
    )
    painter.end()
    return pixmap


def show_startup_splash(app: QApplication, *, message: str = "Loading…") -> QSplashScreen:
    """Show a dark splash immediately and force a paint before heavy init."""
    splash = QSplashScreen(create_splash_pixmap(message=message))
    splash.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    splash.show()
    app.processEvents()
    return splash
