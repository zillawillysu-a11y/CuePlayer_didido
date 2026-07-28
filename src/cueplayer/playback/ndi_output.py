"""Optional NDI video sender for Clean Video Output frames.

Uses ``cyndilib`` when installed (``pip install cyndilib`` or ``pip install -e ".[ndi]"``).
Without the library or NDI Runtime, configure() returns a clear error and send is a no-op.

Frame modes
-----------
``video``
    NDI resolution follows the decoded video frame (source / decode-quality size).
``output_window``
    NDI canvas matches the Clean Output content size, composed with Fit/Fill
    like the on-screen preview (what you see in the Output box).
"""

from __future__ import annotations

import logging
import threading
from fractions import Fraction
from typing import Any, Literal

import numpy as np

log = logging.getLogger(__name__)

NdiFrameMode = Literal["video", "output_window"]

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


def _fit_rgb(rgb: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """Letterbox (Fit): whole frame visible, black bars if needed."""
    out = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    h, w = int(rgb.shape[0]), int(rgb.shape[1])
    if h <= 0 or w <= 0:
        return out
    scale = min(out_w / w, out_h / h)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    y_idx = np.clip((np.arange(nh) * h / nh).astype(np.int32), 0, h - 1)
    x_idx = np.clip((np.arange(nw) * w / nw).astype(np.int32), 0, w - 1)
    scaled = rgb[y_idx][:, x_idx]
    x0 = (out_w - nw) // 2
    y0 = (out_h - nh) // 2
    out[y0 : y0 + nh, x0 : x0 + nw] = scaled
    return out


def _fill_rgb(rgb: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """Cover (Fill): crop to fill the canvas, no black bars."""
    h, w = int(rgb.shape[0]), int(rgb.shape[1])
    if h <= 0 or w <= 0:
        return np.zeros((out_h, out_w, 3), dtype=np.uint8)
    scale = max(out_w / w, out_h / h)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    y_idx = np.clip((np.arange(nh) * h / nh).astype(np.int32), 0, h - 1)
    x_idx = np.clip((np.arange(nw) * w / nw).astype(np.int32), 0, w - 1)
    scaled = rgb[y_idx][:, x_idx]
    x0 = max(0, (nw - out_w) // 2)
    y0 = max(0, (nh - out_h) // 2)
    return np.ascontiguousarray(scaled[y0 : y0 + out_h, x0 : x0 + out_w])


def _compose_rgb(
    rgb: np.ndarray, out_w: int, out_h: int, *, fit_mode: str
) -> np.ndarray:
    if fit_mode == "fill":
        return _fill_rgb(rgb, out_w, out_h)
    return _fit_rgb(rgb, out_w, out_h)


def _pack_rgbx_into(dst: np.ndarray, rgb: np.ndarray) -> None:
    h, w, _ = rgb.shape
    view = dst.reshape(h, w, 4)
    view[:, :, :3] = rgb[:, :, :3]
    view[:, :, 3] = 255


def _even(n: int) -> int:
    n = max(16, int(n))
    return n - (n % 2)


class NdiVideoOutput:
    """Send RGB24 frames on the same path as Clean Video Output (no second decoder)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._enabled = False
        self._name = "CuePlayer"
        self._frame_mode: NdiFrameMode = "output_window"
        self._fit_mode = "fit"
        self._sender: Any = None
        self._frame: Any = None
        self._width = _DEFAULT_W
        self._height = _DEFAULT_H
        self._last_error = ""
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
    def frame_mode(self) -> NdiFrameMode:
        with self._lock:
            return self._frame_mode

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def configure(
        self,
        *,
        enabled: bool,
        name: str = "CuePlayer",
        frame_mode: str = "output_window",
        width: int = _DEFAULT_W,
        height: int = _DEFAULT_H,
        fit_mode: str = "fit",
    ) -> str | None:
        with self._lock:
            self._enabled = bool(enabled)
            self._name = (name or "CuePlayer").strip() or "CuePlayer"
            mode = str(frame_mode or "output_window")
            self._frame_mode = "video" if mode == "video" else "output_window"
            self._fit_mode = "fill" if fit_mode == "fill" else "fit"
            self._width = _even(width)
            self._height = _even(height)
            self._close_locked()
            if not self._enabled:
                self._last_error = ""
                return None
            if not ndi_available():
                self._enabled = False
                self._last_error = ndi_status()
                return self._last_error
            return self._open_locked()

    def set_presentation(
        self, *, width: int, height: int, fit_mode: str = "fit"
    ) -> None:
        """Update Output-window canvas / Fit-Fill without toggling enable."""
        with self._lock:
            self._fit_mode = "fill" if fit_mode == "fill" else "fit"
            if self._frame_mode != "output_window" or not self._enabled:
                return
            w, h = _even(width), _even(height)
            if (w, h) == (self._width, self._height):
                return
            self._width = w
            self._height = h
            if self._sender is None:
                return
            # Resolution change requires a fresh sender in cyndilib.
            self._close_locked()
            self._enabled = True
            err = self._open_locked()
            if err:
                log.warning("NDI reopen after resize failed: %s", err)

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
                    rgb = rgb[:, :, :3]
                    if self._frame_mode == "video":
                        h, w = int(rgb.shape[0]), int(rgb.shape[1])
                        w, h = _even(w), _even(h)
                        if (w, h) != (self._width, self._height):
                            self._width = w
                            self._height = h
                            self._close_locked()
                            self._enabled = True
                            err = self._open_locked()
                            if err or self._sender is None:
                                return
                        # Crop/pad 1px if odd→even changed size slightly.
                        canvas = np.zeros((self._height, self._width, 3), dtype=np.uint8)
                        ch = min(self._height, rgb.shape[0])
                        cw = min(self._width, rgb.shape[1])
                        canvas[:ch, :cw] = rgb[:ch, :cw]
                    else:
                        if (
                            rgb.shape[0] == self._height
                            and rgb.shape[1] == self._width
                        ):
                            canvas = rgb
                        else:
                            canvas = _compose_rgb(
                                rgb,
                                self._width,
                                self._height,
                                fit_mode=self._fit_mode,
                            )

                dst = self._buf_a if self._use_a else self._buf_b
                if dst is None or dst.size != self._width * self._height * 4:
                    return
                _pack_rgbx_into(dst, canvas)
                self._use_a = not self._use_a

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

    def _open_locked(self) -> str | None:
        try:
            from cyndilib.sender import Sender
            from cyndilib.video_frame import VideoSendFrame
            from cyndilib.wrapper.ndi_structs import FourCC

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
