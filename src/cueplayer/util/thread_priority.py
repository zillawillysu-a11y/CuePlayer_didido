"""Lower CPU priority for background audio/BPM workers."""

from __future__ import annotations

import os
import sys


def lower_background_thread_priority() -> None:
    """Best-effort: keep heavy workers from starving the rest of the desktop."""
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            # THREAD_PRIORITY_BELOW_NORMAL
            kernel32.SetThreadPriority(kernel32.GetCurrentThread(), -1)
        except Exception:  # noqa: BLE001
            pass
        return
    try:
        os.nice(10)
    except (OSError, AttributeError):
        pass
