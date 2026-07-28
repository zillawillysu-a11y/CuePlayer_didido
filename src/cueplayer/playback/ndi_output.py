"""Optional NDI video sender for Clean Video Output frames.

Uses ``cyndilib`` when installed (``pip install cyndilib`` or ``pip install -e ".[ndi]"``).
Without the library or NDI Runtime, configure() returns a clear error and send is a no-op.
"""

from __future__ import annotations

import logging
import threading
from fractions import Fraction
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


def _rgb_to_rgbx_bytes(rgb: np.ndarray) -> np.ndarray:
    """Pack HxWx3 RGB24 into contiguous RGBX (A=255) uint8 flat buffer for NDI."""
    h, w, _ = rgb.shape
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[:, :, :3] = rgb[:, :, :3]
    out[:, :, 3] = 255
    return np.ascontiguousarray(out).reshape(-1)


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

                # clock_video=False: CuePlayer already paces frames from the
                # audio sample clock; do not let NDI add a second rate limiter.
                sender = Sender(self._name, clock_video=False)
                frame = VideoSendFrame()
                frame.set_resolution(1920, 1080)
                # cyndilib expects a single Fraction, not (num, den) args.
                frame.set_frame_rate(Fraction(30, 1))
                frame.set_fourcc(FourCC.RGBX)
                sender.set_video_frame(frame)
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
                if rgb.dtype != np.uint8:
                    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
                if (w, h) != (self._width, self._height):
                    # Resolution must be set before the next write.
                    self._frame.set_resolution(w, h)
                    self._width = w
                    self._height = h
                payload = _rgb_to_rgbx_bytes(rgb)
                write_async = getattr(self._sender, "write_video_async", None)
                if callable(write_async):
                    write_async(payload)
                    return
                write = getattr(self._sender, "write_video", None)
                if callable(write):
                    write(payload)
                    return
                # Older fallback path.
                self._frame.write_data(payload)
                self._sender.send_video_async()
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
