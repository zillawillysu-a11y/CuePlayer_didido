"""Application entrypoint."""

from __future__ import annotations

import os
import sys
import traceback

# Load PortAudio's ASIO backend on Windows (Reaper-style) before sounddevice import.
if sys.platform == "win32":
    os.environ.setdefault("SD_ENABLE_ASIO", "1")


def main() -> int:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from cueplayer.ui.main_window import MainWindow
    from cueplayer.ui.splash import show_startup_splash
    from cueplayer.ui.theme import BG_APP, apply_dark_palette, build_stylesheet

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("CuePlayer")
    app.setOrganizationName("CuePlayer")
    # Keep process alive until the main window is shown (splash alone must not
    # quit the app if something races during boot).
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")

    splash = show_startup_splash(app, message="Starting…")
    splash.set_progress(0.08, "Applying theme…")
    apply_dark_palette(app)
    app.setStyleSheet(build_stylesheet())

    splash.set_progress(0.18, "Loading color presets…")
    try:
        from cueplayer.ui.color_presets import restore_color_dialog_customs

        restore_color_dialog_customs()
    except Exception:  # noqa: BLE001
        traceback.print_exc()

    splash.set_progress(0.28, "Building main window…")
    try:
        window = MainWindow()
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        splash.close()
        QMessageBox.critical(
            None,
            "CuePlayer failed to start",
            f"Main window could not be created:\n\n{exc}",
        )
        return 1

    window.setStyleSheet(f"QMainWindow {{ background-color: {BG_APP}; }}")
    splash.set_progress(0.7, "Opening…")

    shown = {"done": False}

    def _show_main() -> None:
        if shown["done"]:
            return
        shown["done"] = True
        splash.set_progress(1.0, "Ready")
        window.show()
        window.raise_()
        window.activateWindow()
        try:
            window.present_clean_output_for_obs()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        splash.finish(window)
        app.setQuitOnLastWindowClosed(True)

    # Always open the main window — do not depend on session-restore signals.
    # Restore can be slow or fail on a machine; the UI must still appear.
    window.startup_ready.connect(_show_main)
    if window.startup_session_ready:
        QTimer.singleShot(0, _show_main)
    else:
        # Show as soon as the event loop starts; restore continues underneath.
        QTimer.singleShot(0, _show_main)
    # Absolute fallback if timers were somehow starved.
    QTimer.singleShot(3000, _show_main)

    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "CuePlayer crashed", str(exc))
        except Exception:  # noqa: BLE001
            pass
        raise SystemExit(1)
