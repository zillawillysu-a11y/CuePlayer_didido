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

    window = MainWindow()
    window.show()
    # If Clean Output was restored during init, show it again after the main
    # window so OBS Window Capture keeps matching "CuePlayer Clean Video Output".
    QTimer.singleShot(0, window.present_clean_output_for_obs)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
