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

# Stable NDI canvas (letterboxed). Changing resolution mid-stream confuses
# receivers like Depence; Clean Output may be smaller — we scale into this.
_DEFAULT_W = 1920
_DEFAULT_H = 1080


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


def _letterbox_rgb(rgb: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """Nearest-neighbor fit of HxWx3 into out_h x out_w with black bars."""
    out = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    h, w = int(rgb.shape[0]), int(rgb.shape[1])
    if h <= 0 or w <= 0:
        return out
    scale = min(out_w / w, out_h / h)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    # Nearest-neighbor resize without extra deps.
    y_idx = (np.arange(nh) * h / nh).astype(np.int32)
    x_idx = (np.arange(nw) * w / nw).astype(np.int32)
    y_idx = np.clip(y_idx, 0, h - 1)
    x_idx = np.clip(x_idx, 0, w - 1)
    scaled = rgb[y_idx][:, x_idx]
    x0 = (out_w - nw) // 2
    y0 = (out_h - nh) // 2
    out[y0 : y0 + nh, x0 : x0 + nw] = scaled
    return out


def _pack_rgbx_into(dst: np.ndarray, rgb: np.ndarray) -> None:
    """Fill flat RGBX uint8 buffer (len = H*W*4) from HxWx3 RGB."""
    h, w, _ = rgb.shape
    view = dst.reshape(h, w, 4)
    view[:, :, :3] = rgb[:, :, :3]
    view[:, :, 3] = 255


class NdiVideoOutput:
    """Send RGB24 frames on the same path as Clean Video Output (no second decoder)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._enabled = False
        self._name = "CuePlayer"
        self._sender: Any = None
        self._frame: Any = None
        self._width = _DEFAULT_W
        self._height = _DEFAULT_H
        self._last_error = ""
        # Persistent buffers for async-safe sending (NDI may read until next call).
        self._buf_a: np.ndarray | None = None
        self._buf_b: np.ndarray | None = None
        self._use_a = True
        self._send_failures = 0

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled and self._sender is not None

    @property
    def name(self) -> str:
        with self._lock:
            return self._name

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def configure(
        self,
        *,
        enabled: bool,
        name: str = "CuePlayer",
        width: int = _DEFAULT_W,
        height: int = _DEFAULT_H,
    ) -> str | None:
        with self._lock:
            self._enabled = bool(enabled)
            self._name = (name or "CuePlayer").strip() or "CuePlayer"
            self._width = max(16, int(width) or _DEFAULT_W)
            self._height = max(16, int(height) or _DEFAULT_H)
            # Keep 16:9-ish even sizes for NDI.
            self._width -= self._width % 2
            self._height -= self._height % 2
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

                # clock_video=False: CuePlayer already paces from the audio clock.
                sender = Sender(self._name, clock_video=False)
                frame = VideoSendFrame()
                frame.set_resolution(self._width, self._height)
                frame.set_frame_rate(Fraction(30, 1))
                frame.set_fourcc(FourCC.RGBX)
                sender.set_video_frame(frame)
                sender.open()
                nbytes = self._width * self._height * 4
                self._buf_a = np.zeros(nbytes, dtype=np.uint8)
                self._buf_b = np.zeros(nbytes, dtype=np.uint8)
                self._use_a = True
                self._sender = sender
                self._frame = frame
                self._last_error = ""
                self._send_failures = 0
                return None
            except Exception as exc:  # noqa: BLE001
                self._enabled = False
                self._sender = None
                self._frame = None
                self._buf_a = None
                self._buf_b = None
                self._last_error = f"NDI open failed: {exc}"
                log.warning("NDI configure failed: %s", exc)
                return self._last_error

    def send_frame(self, frame: np.ndarray | None) -> None:
        with self._lock:
            if not self._enabled or self._sender is None:
                return
            try:
                if frame is None:
                    canvas = np.zeros((self._height, self._width, 3), dtype=np.uint8)
                else:
                    rgb = np.asarray(frame)
                    if rgb.ndim != 3 or rgb.shape[2] < 3:
                        return
                    if rgb.dtype != np.uint8:
                        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
                    if rgb.shape[0] == self._height and rgb.shape[1] == self._width:
                        canvas = rgb[:, :, :3]
                    else:
                        canvas = _letterbox_rgb(rgb[:, :, :3], self._width, self._height)

                # Double-buffer so async NDI can still read the previous frame.
                dst = self._buf_a if self._use_a else self._buf_b
                if dst is None or dst.size != self._width * self._height * 4:
                    return
                _pack_rgbx_into(dst, canvas)
                self._use_a = not self._use_a

                # Prefer sync write — copies into NDI before return.
                write = getattr(self._sender, "write_video", None)
                if callable(write):
                    write(dst)
                    return
                write_async = getattr(self._sender, "write_video_async", None)
                if callable(write_async):
                    write_async(dst)
                    return
                if self._frame is not None:
                    self._frame.write_data(dst)
                    self._sender.send_video()
            except Exception as exc:  # noqa: BLE001
                self._send_failures += 1
                if self._send_failures <= 3 or self._send_failures % 120 == 0:
                    log.warning("NDI send_frame failed: %s", exc)
                    self._last_error = f"NDI send failed: {exc}"

    def close(self) -> None:
        with self._lock:
            self._enabled = False
            self._close_locked()

    def _close_locked(self) -> None:
        sender = self._sender
        self._sender = None
        self._frame = None
        self._buf_a = None
        self._buf_b = None
        if sender is None:
            return
        try:
            if hasattr(sender, "close"):
                sender.close()
        except Exception:  # noqa: BLE001
            pass
