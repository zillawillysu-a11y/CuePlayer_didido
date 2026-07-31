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

from PySide6.QtCore import QPoint, Qt, QTimer, Signal, QSize
from PySide6.QtGui import QCloseEvent, QHideEvent, QResizeEvent, QShowEvent
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QInputDialog, QMenu, QVBoxLayout, QWidget

from cueplayer.domain.models import CleanVideoOutputSettings, VIDEO_DECODE_QUALITY_MAX_HEIGHT
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


_DECODE_QUALITY_LABELS: tuple[tuple[str, str], ...] = (
    ("full", "Full (source resolution)"),
    ("1080p", "1080p"),
    ("720p", "720p"),
    ("540p", "540p"),
)


def content_size_for_aspect(
    client_w: int, client_h: int, *, prefer_width: bool
) -> tuple[int, int]:
    """16:9 content size that fits inside a client area, following the dominant drag axis."""
    client_w = max(1, int(client_w))
    client_h = max(1, int(client_h))
    if prefer_width:
        return client_w, max(1, round(client_w * _ASPECT_H / _ASPECT_W))
    return max(1, round(client_h * _ASPECT_W / _ASPECT_H)), client_h


class CleanVideoOutputWindow(QWidget):
    visibility_changed = Signal(bool)
    # Content size or aspect-lock state changed; main_window marks the
    # project dirty on this (actual persistence happens at save time via
    # current_settings()).
    settings_changed = Signal()
    decode_quality_changed = Signal(str)  # emitted when user picks a quality in this menu
    ndi_toggled = Signal(bool)
    ndi_name_changed = Signal(str)
    ndi_frame_mode_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(CLEAN_OUTPUT_WINDOW_TITLE)
        # Stable OBS target: do not steal activation from the main editor.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._aspect_locked = True
        self._adjusting = False
        self._last_frame_pos: QPoint | None = None
        self._decode_quality: str = "1080p"
        self._ndi_enabled = False
        self._ndi_name = "CuePlayer"
        self._ndi_frame_mode = "output_window"
        # Normally the X button only hides this window (see closeEvent) so
        # that re-opening from the Tools menu keeps the same OBS capture
        # target valid. force_close() flips this so MainWindow can actually
        # tear it down (and let the app quit) when the app itself closes.
        self._force_closing = False
        self._settings_debounce = QTimer(self)
        self._settings_debounce.setSingleShot(True)
        self._settings_debounce.setInterval(300)
        self._settings_debounce.timeout.connect(self.settings_changed.emit)
        self.setStyleSheet("background: black;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # No placeholder text here: unplayed regions must stay pure black
        # for the OBS capture, with no debug text baked into the frame.
        # Keep smooth scaling — nearest-neighbor made 1080p Clean Output look
        # far softer/blockier than the Decode Quality setting. Decode caps +
        # long-video preload skips are the primary jank controls now.
        self.preview = VideoPreviewWidget(
            self, placeholder_text="", smooth_scale=True
        )
        layout.addWidget(self.preview)
        self.resize(1920, 1080)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def set_frame(self, frame) -> None:  # noqa: ANN001
        self.preview.set_frame(frame)

    def set_qimage(self, image) -> None:  # noqa: ANN001
        self.preview.set_qimage(image)

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
            self._apply_aspect_from_client(self.width(), self.height(), prefer_width=True)
        self._schedule_settings_changed()

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
        self._schedule_settings_changed()

    def current_settings(self) -> CleanVideoOutputSettings:
        width, height = self.content_size()
        return CleanVideoOutputSettings(
            width=width,
            height=height,
            aspect_locked=self._aspect_locked,
            was_open=self.isVisible(),
            ndi_enabled=bool(self._ndi_enabled),
            ndi_name=str(self._ndi_name or "CuePlayer"),
            ndi_frame_mode=str(self._ndi_frame_mode or "output_window"),
        )

    def apply_settings(self, settings: CleanVideoOutputSettings) -> None:
        self._aspect_locked = bool(settings.aspect_locked)
        self._ndi_enabled = bool(getattr(settings, "ndi_enabled", False))
        self._ndi_name = str(getattr(settings, "ndi_name", "") or "CuePlayer")
        mode = str(getattr(settings, "ndi_frame_mode", "") or "output_window")
        self._ndi_frame_mode = "video" if mode == "video" else "output_window"
        self.apply_preset(settings.width, settings.height)

    def set_ndi_enabled(self, enabled: bool) -> None:
        self._ndi_enabled = bool(enabled)

    def ndi_enabled(self) -> bool:
        return bool(self._ndi_enabled)

    def set_ndi_name(self, name: str) -> None:
        self._ndi_name = (name or "").strip() or "CuePlayer"

    def ndi_name(self) -> str:
        return str(self._ndi_name or "CuePlayer")

    def set_ndi_frame_mode(self, mode: str) -> None:
        self._ndi_frame_mode = "video" if mode == "video" else "output_window"

    def ndi_frame_mode(self) -> str:
        return str(self._ndi_frame_mode or "output_window")

    def _schedule_settings_changed(self) -> None:
        self._settings_debounce.start()

    def _release_preview_size_pin(self) -> None:
        self.preview.setMinimumSize(0, 0)
        self.preview.setMaximumSize(_QWIDGETSIZE_MAX, _QWIDGETSIZE_MAX)

    def _apply_aspect_from_client(
        self, client_w: int, client_h: int, *, prefer_width: bool
    ) -> None:
        cw, ch = content_size_for_aspect(client_w, client_h, prefer_width=prefer_width)
        self._adjusting = True
        try:
            self.preview.setFixedSize(cw, ch)
            self.adjustSize()
        finally:
            self._release_preview_size_pin()
            self._adjusting = False

    def _handle_aspect_locked_resize(self, event: QResizeEvent) -> None:
        old_size = event.oldSize()
        new_size = event.size()
        if not old_size.isValid() or old_size == new_size:
            return

        dw = new_size.width() - old_size.width()
        dh = new_size.height() - old_size.height()
        prefer_width = abs(dw) >= abs(dh)

        frame_tl = self.frameGeometry().topLeft()
        anchor_bottom_right = (
            self._last_frame_pos is not None and frame_tl != self._last_frame_pos
        )
        br_before = self.frameGeometry().bottomRight()

        cw, ch = content_size_for_aspect(
            new_size.width(), new_size.height(), prefer_width=prefer_width
        )

        self._adjusting = True
        try:
            self.preview.setFixedSize(cw, ch)
            self.adjustSize()
            if anchor_bottom_right:
                frame = self.frameGeometry()
                self.move(
                    br_before.x() - frame.width() + 1,
                    br_before.y() - frame.height() + 1,
                )
        finally:
            self._release_preview_size_pin()
            self._adjusting = False
            self._last_frame_pos = self.frameGeometry().topLeft()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        if self._adjusting:
            super().resizeEvent(event)
            return
        if self._aspect_locked:
            self._handle_aspect_locked_resize(event)
        else:
            super().resizeEvent(event)
        self._schedule_settings_changed()

    def present_for_obs_capture(self) -> None:
        """Show Clean Output with a stable title for OBS Window Capture."""
        self.setWindowTitle(CLEAN_OUTPUT_WINDOW_TITLE)
        if not self.isVisible():
            self.show()
        # Do not raise_() here — staying above the main editor made OBS pick
        # this window when the user intended to capture "CuePlayer Main".

    def current_decode_quality(self) -> str:
        return self._decode_quality

    def set_decode_quality(self, quality: str) -> None:
        if quality in VIDEO_DECODE_QUALITY_MAX_HEIGHT:
            self._decode_quality = quality

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
        quality_menu = menu.addMenu("Video Decode Quality")
        quality_group = QActionGroup(self)
        quality_group.setExclusive(True)
        quality_actions: dict[object, str] = {}
        for q_key, q_label in _DECODE_QUALITY_LABELS:
            qa = quality_menu.addAction(q_label)
            qa.setCheckable(True)
            qa.setChecked(q_key == self._decode_quality)
            quality_group.addAction(qa)
            quality_actions[qa] = q_key

        menu.addSeparator()
        ndi_action = menu.addAction("NDI Output")
        ndi_action.setCheckable(True)
        ndi_action.setChecked(bool(self._ndi_enabled))
        ndi_action.setToolTip("Send this Clean Output picture over NDI (Depence / etc.)")
        ndi_name_action = menu.addAction(f"NDI Name: {self._ndi_name}…")
        ndi_name_action.setToolTip("Custom NDI source name so Depence does not pick the wrong feed")
        ndi_mode_menu = menu.addMenu("NDI Frame Size")
        ndi_mode_group = QActionGroup(self)
        ndi_mode_group.setExclusive(True)
        ndi_mode_video = ndi_mode_menu.addAction("Video (source / decode size)")
        ndi_mode_video.setCheckable(True)
        ndi_mode_video.setToolTip("NDI resolution follows the decoded video frame")
        ndi_mode_window = ndi_mode_menu.addAction("Output window (Fit / Fill)")
        ndi_mode_window.setCheckable(True)
        ndi_mode_window.setToolTip(
            "NDI matches this window’s size and Fit/Fill — same picture as the Output box"
        )
        ndi_mode_group.addAction(ndi_mode_video)
        ndi_mode_group.addAction(ndi_mode_window)
        if self._ndi_frame_mode == "video":
            ndi_mode_video.setChecked(True)
        else:
            ndi_mode_window.setChecked(True)

        menu.addSeparator()
        fullscreen_action = menu.addAction("Exit Fullscreen" if self.isFullScreen() else "Fullscreen")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is fit_action:
            self.preview.set_fit_mode("fit")
            self._schedule_settings_changed()
        elif chosen is fill_action:
            self.preview.set_fit_mode("fill")
            self._schedule_settings_changed()
        elif chosen is lock_action:
            self.set_aspect_locked(lock_action.isChecked())
        elif chosen in preset_actions:
            width, height = preset_actions[chosen]
            self.apply_preset(width, height)
        elif chosen in quality_actions:
            quality = quality_actions[chosen]
            self._decode_quality = quality
            self.decode_quality_changed.emit(quality)
        elif chosen is ndi_action:
            enabled = bool(ndi_action.isChecked())
            self._ndi_enabled = enabled
            self.ndi_toggled.emit(enabled)
        elif chosen is ndi_name_action:
            self._prompt_ndi_name()
        elif chosen is ndi_mode_video:
            self._ndi_frame_mode = "video"
            self.ndi_frame_mode_changed.emit("video")
            self._schedule_settings_changed()
        elif chosen is ndi_mode_window:
            self._ndi_frame_mode = "output_window"
            self.ndi_frame_mode_changed.emit("output_window")
            self._schedule_settings_changed()
        elif chosen is fullscreen_action:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()

    def _prompt_ndi_name(self) -> None:
        text, ok = QInputDialog.getText(
            self,
            "NDI Source Name",
            "Name shown in Depence / NDI receivers:",
            text=self._ndi_name,
        )
        if not ok:
            return
        name = (text or "").strip() or "CuePlayer"
        if name == self._ndi_name:
            return
        self._ndi_name = name
        self.ndi_name_changed.emit(name)
        self._schedule_settings_changed()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self._last_frame_pos = None
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
