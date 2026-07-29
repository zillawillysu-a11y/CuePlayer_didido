"""Dark startup splash — avoids a blank white window while CuePlayer loads."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from cueplayer.ui.theme import ACCENT, BG_APP, BORDER, TEXT, TEXT_MUTED


def create_splash_pixmap(
    *,
    width: int = 520,
    height: int = 300,
    message: str = "Loading…",
    progress: float = 0.0,
    fullscreen: bool = False,
) -> QPixmap:
    """Paint a CuePlayer-branded dark splash with a real progress bar."""
    pixmap = QPixmap(max(320, width), max(200, height))
    pixmap.fill(QColor(BG_APP))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    if not fullscreen:
        painter.setPen(QColor(BORDER))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(pixmap.rect().adjusted(1, 1, -2, -2), 12, 12)

    title = "CuePlayer"
    title_font = QFont()
    title_font.setFamilies(["Segoe UI", "Microsoft JhengHei UI", "Arial"])
    title_font.setPixelSize(34)
    title_font.setWeight(QFont.Weight.DemiBold)

    msg_font = QFont()
    msg_font.setFamilies(["Segoe UI", "Microsoft JhengHei UI", "Arial"])
    msg_font.setPixelSize(13)

    title_metrics = QFontMetrics(title_font)
    msg_metrics = QFontMetrics(msg_font)
    title_block = title_metrics.boundingRect(title)
    msg_block = msg_metrics.boundingRect(message)

    gap_title_bar = 14
    bar_height = 4
    bar_width = min(220, max(120, width // 5))
    gap_bar_msg = 18
    block_h = (
        title_block.height()
        + gap_title_bar
        + bar_height
        + gap_bar_msg
        + msg_block.height()
    )
    top_y = max(24, (height - block_h) // 2)

    painter.setFont(title_font)
    painter.setPen(QColor(TEXT))
    painter.drawText(
        0,
        top_y,
        width,
        title_block.height(),
        int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
        title,
    )

    bar_y = top_y + title_block.height() + gap_title_bar
    bar_x = width // 2 - bar_width // 2
    # Track (empty).
    painter.fillRect(bar_x, bar_y, bar_width, bar_height, QColor(BORDER))
    # Fill (0…100%).
    fill = max(0.0, min(1.0, float(progress)))
    fill_w = max(0, int(round(bar_width * fill)))
    if fill_w > 0:
        painter.fillRect(bar_x, bar_y, fill_w, bar_height, QColor(ACCENT))

    painter.setFont(msg_font)
    painter.setPen(QColor(TEXT_MUTED))
    painter.drawText(
        0,
        bar_y + bar_height + gap_bar_msg,
        width,
        msg_block.height(),
        int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
        message,
    )
    painter.end()
    return pixmap


class StartupSplash(QSplashScreen):
    """Centered splash that can update loading progress while the app boots."""

    _WINDOW_WIDTH = 520
    _WINDOW_HEIGHT = 300

    def __init__(self, app: QApplication, *, message: str = "Loading…") -> None:
        self._width = self._WINDOW_WIDTH
        self._height = self._WINDOW_HEIGHT
        self._fullscreen = False
        pixmap = create_splash_pixmap(
            width=self._width,
            height=self._height,
            message=message,
            progress=0.0,
            fullscreen=False,
        )
        super().__init__(pixmap)

        screen = app.primaryScreen()
        geo = screen.availableGeometry() if screen is not None else None
        if geo is not None:
            x = geo.x() + max(0, (geo.width() - self._width) // 2)
            y = geo.y() + max(0, (geo.height() - self._height) // 2)
            self.setGeometry(x, y, self._width, self._height)

        self._message = message
        self._progress = 0.0
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

    def set_progress(self, progress: float, message: str | None = None) -> None:
        self._progress = max(0.0, min(1.0, float(progress)))
        if message is not None:
            self._message = message
        pixmap = create_splash_pixmap(
            width=self._width,
            height=self._height,
            message=self._message,
            progress=self._progress,
            fullscreen=self._fullscreen,
        )
        self.setPixmap(pixmap)
        QApplication.processEvents()


def show_startup_splash(app: QApplication, *, message: str = "Loading…") -> StartupSplash:
    """Show a centered dark splash immediately and force a paint before heavy init."""
    splash = StartupSplash(app, message=message)
    splash.show()
    splash.set_progress(0.0, message)
    return splash
