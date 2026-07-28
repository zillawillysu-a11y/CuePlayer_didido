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

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("CuePlayer")
    app.setOrganizationName("CuePlayer")
    app.setQuitOnLastWindowClosed(True)
    app.setStyle("Fusion")

    splash = show_startup_splash(app, message="Starting…")
    splash.set_progress(0.08, "Applying theme…")
    apply_dark_palette(app)
    app.setStyleSheet(build_stylesheet())

    splash.set_progress(0.18, "Loading color presets…")
    from cueplayer.ui.color_presets import restore_color_dialog_customs

    restore_color_dialog_customs()

    splash.set_progress(0.28, "Building main window…")

    finished = {"done": False}

    def _on_startup_ready() -> None:
        if finished["done"]:
            return
        finished["done"] = True
        splash.set_progress(0.92, "Opening…")
        window.present_clean_output_for_obs()

        def _finish() -> None:
            splash.set_progress(1.0, "Ready")
            window.show()
            splash.finish(window)

        # Brief beat at 100% so the fill is visible before splash closes.
        QTimer.singleShot(120, _finish)

    # Connect BEFORE any processEvents after MainWindow exists — splash
    # set_progress() pumps the event loop and can emit startup_ready early.
    window = MainWindow()
    window.startup_ready.connect(_on_startup_ready)
    window.setStyleSheet(f"QMainWindow {{ background-color: {BG_APP}; }}")
    splash.set_progress(0.55, "Restoring session…")

    # If restore already finished during the progress update, open now.
    if window.startup_session_ready:
        QTimer.singleShot(0, _on_startup_ready)

    # Safety: never leave the user stuck on splash if the ready signal is missed.
    QTimer.singleShot(8000, _on_startup_ready)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
