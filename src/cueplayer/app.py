"""Application entrypoint."""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Load PortAudio's ASIO backend on Windows (Reaper-style) before sounddevice import.
if sys.platform == "win32":
    os.environ.setdefault("SD_ENABLE_ASIO", "1")


def _boot_log_path() -> Path:
    # Always writable on Windows; also copy hint into cwd when possible.
    return Path(tempfile.gettempdir()) / "cueplayer_startup.log"


def _boot_log(message: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()}  {message}"
    print(line, flush=True)
    path = _boot_log_path()
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass
    # Convenience copy next to where the user launched from.
    try:
        cwd_copy = Path.cwd() / "startup_error.txt"
        with cwd_copy.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    _boot_log(f"CuePlayer boot start  python={sys.executable}  cwd={Path.cwd()}")
    _boot_log(f"argv={sys.argv!r}")
    try:
        import cueplayer

        _boot_log(f"cueplayer package={getattr(cueplayer, '__file__', '?')}")
    except Exception as exc:  # noqa: BLE001
        _boot_log(f"cueplayer import failed: {exc}")

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from cueplayer.ui.main_window import MainWindow
    from cueplayer.ui.splash import show_startup_splash
    from cueplayer.ui.theme import BG_APP, apply_dark_palette, apply_ui_font, build_stylesheet

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
    _boot_log("QApplication ready")

    splash = show_startup_splash(app, message="Starting…")
    splash.set_progress(0.08, "Applying theme…")
    apply_ui_font(app)
    apply_dark_palette(app)
    app.setStyleSheet(build_stylesheet())

    splash.set_progress(0.18, "Loading color presets…")
    try:
        from cueplayer.ui.color_presets import restore_color_dialog_customs

        restore_color_dialog_customs()
        _boot_log("color presets restored")
    except Exception:  # noqa: BLE001
        _boot_log("color presets failed:\n" + traceback.format_exc())

    splash.set_progress(0.28, "Building main window…")
    _boot_log("creating MainWindow…")
    try:
        window = MainWindow()
    except Exception as exc:  # noqa: BLE001
        _boot_log("MainWindow failed:\n" + traceback.format_exc())
        splash.close()
        QMessageBox.critical(
            None,
            "CuePlayer failed to start",
            f"Main window could not be created:\n\n{exc}\n\n"
            f"Log: {_boot_log_path()}",
        )
        return 1
    _boot_log("MainWindow created")

    window.setStyleSheet(f"QMainWindow {{ background-color: {BG_APP}; }}")
    splash.set_progress(0.7, "Opening…")

    shown = {"done": False}

    def _ensure_on_screen() -> None:
        screen = app.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        frame = window.frameGeometry()
        if geo.intersects(frame):
            return
        # Last session was on a disconnected monitor — pull back to primary.
        window.move(geo.x() + 40, geo.y() + 40)
        _boot_log(f"moved window onto primary screen {geo}")

    def _show_main() -> None:
        if shown["done"]:
            return
        shown["done"] = True
        _boot_log("showing main window")
        splash.set_progress(1.0, "Ready")
        window.show()
        _ensure_on_screen()
        window.raise_()
        window.activateWindow()
        try:
            window.present_clean_output_for_obs()
        except Exception:  # noqa: BLE001
            _boot_log("present_clean_output failed:\n" + traceback.format_exc())
        splash.finish(window)
        app.setQuitOnLastWindowClosed(True)
        _boot_log(f"main window visible={window.isVisible()} size={window.size()}")
        try:
            window.monitor.ensure_now_splitter_ready()
        except Exception:  # noqa: BLE001
            _boot_log("ensure_now_splitter_ready failed:\n" + traceback.format_exc())
        QTimer.singleShot(100, window.monitor.ensure_now_splitter_ready)
        QTimer.singleShot(300, window.monitor.ensure_now_splitter_ready)

    # Always open the main window — do not depend on session-restore signals.
    window.startup_ready.connect(_show_main)
    if window.startup_session_ready:
        QTimer.singleShot(0, _show_main)
    else:
        QTimer.singleShot(0, _show_main)
    QTimer.singleShot(3000, _show_main)

    _boot_log("entering event loop")
    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        _boot_log("fatal:\n" + traceback.format_exc())
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(
                None,
                "CuePlayer crashed",
                f"{exc}\n\nLog: {_boot_log_path()}",
            )
        except Exception:  # noqa: BLE001
            pass
        raise SystemExit(1)
