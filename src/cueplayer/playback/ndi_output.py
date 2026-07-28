"""Optional NDI video sender for Clean Video Output frames.

Uses ``cyndilib`` when installed (``pip install cyndilib`` or ``pip install -e ".[ndi]"``).
Without the library or NDI Runtime, configure() returns a clear error and send is a no-op.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


def ndi_available() -> bool:
    try:
        import cyndilib  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def ndi_status() -> str:
    if ndi_available():
        return "NDI: cyndilib ready (requires NDI Runtime on this machine)"
    return (
        "NDI library not installed. Install with:\n"
        "  py -m pip install cyndilib\n"
        "Also install NDI Tools / Runtime from ndi.video, then restart CuePlayer."
    )


class NdiVideoOutput:
    """Send RGB24 frames on the same path as Clean Video Output (no second decoder)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._enabled = False
        self._name = "CuePlayer"
        self._sender: Any = None
        self._frame: Any = None
        self._width = 0
        self._height = 0
        self._last_error = ""

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled and self._sender is not None

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def configure(self, *, enabled: bool, name: str = "CuePlayer") -> str | None:
        with self._lock:
            self._enabled = bool(enabled)
            self._name = (name or "CuePlayer").strip() or "CuePlayer"
            self._close_locked()
            if not self._enabled:
                self._last_error = ""
                return None
            if not ndi_available():
                self._enabled = False
                self._last_error = ndi_status()
                return self._last_error
            try:
                from cyndilib.sender import Sender
                from cyndilib.video_frame import VideoSendFrame
                from cyndilib.wrapper.ndi_structs import FourCC

                sender = Sender(self._name)
                frame = VideoSendFrame()
                frame.set_resolution(1920, 1080)
                frame.set_frame_rate(30, 1)
                try:
                    frame.set_fourcc(FourCC.RGB)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    try:
                        frame.fourcc = FourCC.RGB  # type: ignore[attr-defined]
                    except Exception:  # noqa: BLE001
                        pass
                sender.set_video_frame(frame)
                if hasattr(sender, "open") and not getattr(sender, "is_open", lambda: True)():
                    sender.open()
                self._sender = sender
                self._frame = frame
                self._width = 1920
                self._height = 1080
                self._last_error = ""
                return None
            except Exception as exc:  # noqa: BLE001
                self._enabled = False
                self._sender = None
                self._frame = None
                self._last_error = f"NDI open failed: {exc}"
                log.warning("NDI configure failed: %s", exc)
                return self._last_error

    def send_frame(self, frame: np.ndarray | None) -> None:
        if frame is None:
            return
        with self._lock:
            if not self._enabled or self._sender is None or self._frame is None:
                return
            try:
                rgb = np.asarray(frame)
                if rgb.ndim != 3 or rgb.shape[2] < 3:
                    return
                h, w = int(rgb.shape[0]), int(rgb.shape[1])
                if h <= 0 or w <= 0:
                    return
                if (w, h) != (self._width, self._height):
                    self._frame.set_resolution(w, h)
                    self._width = w
                    self._height = h
                # Contiguous RGB888 bytes.
                if rgb.dtype != np.uint8:
                    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
                if not rgb.flags["C_CONTIGUOUS"]:
                    rgb = np.ascontiguousarray(rgb)
                payload = rgb[:, :, :3]
                write = getattr(self._frame, "write", None)
                if callable(write):
                    write(payload.tobytes())
                else:
                    # Fallback attribute used by some cyndilib builds.
                    self._frame.data = payload  # type: ignore[attr-defined]
                send_video = getattr(self._sender, "send_video", None)
                if callable(send_video):
                    send_video()
                else:
                    self._sender.send(self._frame)
            except Exception as exc:  # noqa: BLE001
                log.debug("NDI send_frame failed: %s", exc)

    def close(self) -> None:
        with self._lock:
            self._enabled = False
            self._close_locked()

    def _close_locked(self) -> None:
        sender = self._sender
        self._sender = None
        self._frame = None
        self._width = 0
        self._height = 0
        if sender is None:
            return
        try:
            if hasattr(sender, "close"):
                sender.close()
        except Exception:  # noqa: BLE001
            pass
