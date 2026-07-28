"""Application entrypoint."""

from __future__ import annotations

import os
import sys

# Load PortAudio's ASIO backend on Windows (Reaper-style) before sounddevice import.
if sys.platform == "win32":
    os.environ.setdefault("SD_ENABLE_ASIO", "1")


def main() -> int:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication

    from cueplayer.ui.main_window import MainWindow
    from cueplayer.ui.splash import show_startup_splash
    from cueplayer.ui.theme import BG_APP, apply_dark_palette, build_stylesheet

    # Dark chrome before any window is created (reduces Windows white flash).
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

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

    splash = show_startup_splash(app, message="Loading…")

    # Restore QColorDialog custom-color slots (bottom-left presets) from last run.
    from cueplayer.ui.color_presets import restore_color_dialog_customs

    restore_color_dialog_customs()

    window = MainWindow()
    # Ensure the first expose is dark even if children paint a frame late.
    window.setStyleSheet(f"QMainWindow {{ background-color: {BG_APP}; }}")

    # MainWindow queues session restore on singleShot(0). Keep it hidden until
    # restore finishes so the small splash card does not sit on a white window.
    def _after_main_ready() -> None:
        def _finish_splash() -> None:
            window.present_clean_output_for_obs()
            window.show()
            splash.finish(window)

        QTimer.singleShot(0, _finish_splash)

    QTimer.singleShot(0, _after_main_ready)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
