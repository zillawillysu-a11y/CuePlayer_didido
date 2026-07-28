"""Standalone "Clean Video Output" window for OBS Window Capture.

Fixed window title so an OBS Window Capture source keeps pointing at the
right window. Per PRODUCT_SPEC, closing the embedded main Preview must
not interrupt this output, so this window only hides on the close (X)
button instead of being destroyed — re-opening from the Tools menu just
shows it again with the same OBS capture target still valid.

Resolution presets and the aspect-lock toggle live in the right-click
context menu (same place as the existing Fit/Fill/Fullscreen controls)
so no extra chrome is ever drawn inside the capture surface.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QHideEvent, QResizeEvent, QShowEvent
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from cueplayer.domain.models import CleanVideoOutputSettings
from cueplayer.ui.video_preview import VideoPreviewWidget

CLEAN_OUTPUT_WINDOW_TITLE = "CuePlayer Clean Video Output"

# 16:9 family only (AGENTS.md: OBS capture region must not drift off-ratio).
# Ordered largest-first so the context menu reads top-to-bottom as "zoom out".
RESOLUTION_PRESETS: tuple[tuple[str, int, int], ...] = (
    ("1920 × 1080", 1920, 1080),
    ("1280 × 720", 1280, 720),
    ("960 × 540", 960, 540),
    ("640 × 360", 640, 360),
)

_ASPECT_W = 16
_ASPECT_H = 9

# Qt's outer widget maximum; used to release a preset's fixed size afterwards
# so the window stays freely (and, when locked, proportionally) resizable.
_QWIDGETSIZE_MAX = 16777215


class CleanVideoOutputWindow(QWidget):
    visibility_changed = Signal(bool)
    # Content size or aspect-lock state changed; main_window marks the
    # project dirty on this (actual persistence happens at save time via
    # current_settings()).
    settings_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(CLEAN_OUTPUT_WINDOW_TITLE)
        self._aspect_locked = True
        self._adjusting = False
        # Normally the X button only hides this window (see closeEvent) so
        # that re-opening from the Tools menu keeps the same OBS capture
        # target valid. force_close() flips this so MainWindow can actually
        # tear it down (and let the app quit) when the app itself closes.
        self._force_closing = False
        self.setStyleSheet("background: black;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # No placeholder text here: unplayed regions must stay pure black
        # for the OBS capture, with no debug text baked into the frame.
        self.preview = VideoPreviewWidget(self, placeholder_text="")
        layout.addWidget(self.preview)
        self.resize(1920, 1080)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def set_frame(self, frame) -> None:  # noqa: ANN001
        self.preview.set_frame(frame)

    # -- resolution / aspect lock --------------------------------------

    def content_size(self) -> tuple[int, int]:
        """Pixel size of the video content area — the actual OBS capture surface.

        Window chrome (title bar / borders) is decided by the OS and is not
        included here or in saved settings.
        """
        size = self.preview.size()
        return max(1, size.width()), max(1, size.height())

    def aspect_locked(self) -> bool:
        return self._aspect_locked

    def set_aspect_locked(self, locked: bool) -> None:
        locked = bool(locked)
        if locked == self._aspect_locked:
            return
        self._aspect_locked = locked
        if locked:
            self._enforce_aspect_ratio()
        self.settings_changed.emit()

    def apply_preset(self, width: int, height: int) -> None:
        """Snap the content area to an exact pixel size; the window sizes around it."""
        width = max(1, int(width))
        height = max(1, int(height))
        self._adjusting = True
        try:
            self.preview.setFixedSize(width, height)
            self.adjustSize()
        finally:
            # Release the pin so the window remains resizable afterwards
            # (aspect lock, if on, keeps further drags proportional).
            self.preview.setMinimumSize(0, 0)
            self.preview.setMaximumSize(_QWIDGETSIZE_MAX, _QWIDGETSIZE_MAX)
            self._adjusting = False
        self.settings_changed.emit()

    def current_settings(self) -> CleanVideoOutputSettings:
        width, height = self.content_size()
        return CleanVideoOutputSettings(
            width=width,
            height=height,
            aspect_locked=self._aspect_locked,
            was_open=self.isVisible(),
        )

    def apply_settings(self, settings: CleanVideoOutputSettings) -> None:
        self._aspect_locked = bool(settings.aspect_locked)
        self.apply_preset(settings.width, settings.height)

    def _enforce_aspect_ratio(self) -> None:
        if self._adjusting:
            return
        self._adjusting = True
        try:
            width = max(1, self.width())
            target_height = round(width * _ASPECT_H / _ASPECT_W)
            if target_height != self.height():
                self.resize(width, target_height)
        finally:
            self._adjusting = False

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._aspect_locked:
            self._enforce_aspect_ratio()
        self.settings_changed.emit()

    def _show_context_menu(self, pos) -> None:  # noqa: ANN001
        menu = QMenu(self)
        fit_action = menu.addAction("Fit")
        fit_action.setCheckable(True)
        fit_action.setChecked(self.preview.fit_mode() == "fit")
        fill_action = menu.addAction("Fill")
        fill_action.setCheckable(True)
        fill_action.setChecked(self.preview.fit_mode() == "fill")

        menu.addSeparator()
        resolution_menu = menu.addMenu("Resolution")
        current_size = self.content_size()
        preset_actions = {}
        for label, width, height in RESOLUTION_PRESETS:
            action = resolution_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked((width, height) == current_size)
            preset_actions[action] = (width, height)

        lock_action = menu.addAction("Lock Aspect (16:9)")
        lock_action.setCheckable(True)
        lock_action.setChecked(self._aspect_locked)

        menu.addSeparator()
        fullscreen_action = menu.addAction("Exit Fullscreen" if self.isFullScreen() else "Fullscreen")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is fit_action:
            self.preview.set_fit_mode("fit")
        elif chosen is fill_action:
            self.preview.set_fit_mode("fill")
        elif chosen is lock_action:
            self.set_aspect_locked(lock_action.isChecked())
        elif chosen in preset_actions:
            width, height = preset_actions[chosen]
            self.apply_preset(width, height)
        elif chosen is fullscreen_action:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        super().hideEvent(event)
        self.visibility_changed.emit(False)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._force_closing:
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()

    def force_close(self) -> None:
        """Actually close this window instead of just hiding it.

        Used by MainWindow when the whole app is shutting down, so this
        independent top-level window doesn't outlive the main window (and
        doesn't block Qt's "quit on last window closed" behavior).
        """
        if self.isFullScreen():
            self.showNormal()
        self._force_closing = True
        self.hide()
        self.close()
