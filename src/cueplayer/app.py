"""Application entrypoint."""

from __future__ import annotations

import os
import sys

# Load PortAudio's ASIO backend on Windows (Reaper-style) before sounddevice import.
if sys.platform == "win32":
    os.environ.setdefault("SD_ENABLE_ASIO", "1")


def main() -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from cueplayer.ui.main_window import MainWindow
    from cueplayer.ui.theme import apply_dark_palette, build_stylesheet

    app = QApplication(sys.argv)
    app.setApplicationName("CuePlayer")
    app.setOrganizationName("CuePlayer")
    # Single-main-window app: exit when the last visible top-level closes.
    # MainWindow.closeEvent() also tears down Clean Output and calls quit()
    # so a hide-on-X tool window cannot keep the process alive.
    app.setQuitOnLastWindowClosed(True)
    app.setStyle("Fusion")
    apply_dark_palette(app)
    app.setStyleSheet(build_stylesheet())

    # Restore QColorDialog custom-color slots (bottom-left presets) from last run.
    from cueplayer.ui.color_presets import restore_color_dialog_customs

    restore_color_dialog_customs()

    window = MainWindow()
    window.show()
    # Restore Clean Output for OBS if it was open, but keep the main editor on top
    # so Window Capture does not grab the clean feed by mistake.
    def _after_main_show() -> None:
        window.present_clean_output_for_obs()

    QTimer.singleShot(0, _after_main_show)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
