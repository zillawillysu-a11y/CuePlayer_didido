"""Optional NDI video sender for Clean Video Output frames.

Uses ``cyndilib`` when installed. Frame compose + NDI write run on a
background worker so the UI / audio clock thread stays responsive.
"""

from __future__ import annotations

import logging
import sys
import threading
from fractions import Fraction
from typing import Any, Literal

import numpy as np

log = logging.getLogger(__name__)

NdiFrameMode = Literal["video", "output_window"]

_DEFAULT_W = 1920
_DEFAULT_H = 1080

# Official downloads (employees install these; CuePlayer.exe already bundles cyndilib).
NDI_TOOLS_URL = "https://ndi.video/tools/"
NDI_RUNTIME_URL = "https://ndi.link/NDIRedistV6"


def ndi_available() -> bool:
    try:
        import cyndilib  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def ndi_status() -> str:
    if ndi_available():
        return "NDI: cyndilib ready (requires NDI Tools / Runtime on this machine)"
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        return (
            "NDI Tools / Runtime is not installed on this PC "
            "(or this build is missing cyndilib).\n"
            f"Install NDI Tools: {NDI_TOOLS_URL}\n"
            f"Or Runtime only: {NDI_RUNTIME_URL}\n"
            "Then restart CuePlayer."
        )
    return (
        "NDI library not installed. Install with:\n"
        "  py -m pip install cyndilib\n"
        f"Also install NDI Tools ({NDI_TOOLS_URL}) or Runtime "
        f"({NDI_RUNTIME_URL}), then restart CuePlayer."
    )


def ndi_install_required(error: str | None) -> bool:
    """True when the user should install NDI Tools / Runtime (show install dialog)."""
    if not error:
        return False
    if not ndi_available():
        return True
    low = error.lower()
    needles = (
        "runtime",
        "ndi tools",
        "processing.ndi",
        "ndi.lib",
        "processing.ndi.lib",
        "cannot load",
        "failed to load",
        "dll",
        "shared library",
        "not found",
        "no module named",
        "cyndilib",
        "ndi open failed",
    )
    return any(n in low for n in needles)


def ndi_runtime_missing_message(detail: str = "") -> str:
    detail = (detail or "").strip()
    base = (
        "NDI Tools / Runtime is not installed (or could not be loaded) on this PC.\n"
        "Please install NDI, then restart CuePlayer and try NDI Output again."
    )
    if detail:
        return f"{base}\n\nDetail: {detail}"
    return base


def _even(n: int) -> int:
    n = max(16, int(n))
    return n - (n % 2)


def _build_fit_maps(
    src_h: int, src_w: int, out_w: int, out_h: int, *, fit_mode: str
) -> tuple[np.ndarray, np.ndarray, int, int, int, int]:
    """Return (y_idx, x_idx, dst_y0, dst_x0, nh, nw) for nearest-neighbor blit."""
    if fit_mode == "fill":
        scale = max(out_w / src_w, out_h / src_h)
    else:
        scale = min(out_w / src_w, out_h / src_h)
    nw = max(1, int(round(src_w * scale)))
    nh = max(1, int(round(src_h * scale)))
    y_idx = np.clip((np.arange(nh) * src_h / nh).astype(np.int32), 0, src_h - 1)
    x_idx = np.clip((np.arange(nw) * src_w / nw).astype(np.int32), 0, src_w - 1)
    if fit_mode == "fill":
        x0 = max(0, (nw - out_w) // 2)
        y0 = max(0, (nh - out_h) // 2)
        # Crop maps to canvas.
        y_idx = y_idx[y0 : y0 + out_h]
        x_idx = x_idx[x0 : x0 + out_w]
        return y_idx, x_idx, 0, 0, out_h, out_w
    x0 = (out_w - nw) // 2
    y0 = (out_h - nh) // 2
    return y_idx, x_idx, y0, x0, nh, nw


def _pack_rgbx_into(dst: np.ndarray, rgb: np.ndarray) -> None:
    h, w, _ = rgb.shape
    view = dst.reshape(h, w, 4)
    view[:, :, :3] = rgb[:, :, :3]
    view[:, :, 3] = 255


class NdiVideoOutput:
    """Send RGB24 frames; heavy work runs off the UI thread."""

    def __init__(self) -> None:
        self._cfg_lock = threading.RLock()
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

        # Latest-frame slot (UI → worker). Drop intermediate frames.
        self._pending_lock = threading.Lock()
        self._pending_rgb: np.ndarray | None = None  # None = black / no clip
        self._pending_has_black = False
        self._pending_seq = 0
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

        # Cached resize maps (worker only).
        self._map_key: tuple | None = None
        self._map_y: np.ndarray | None = None
        self._map_x: np.ndarray | None = None
        self._map_y0 = 0
        self._map_x0 = 0
        self._map_nh = 0
        self._map_nw = 0
        self._canvas_rgb: np.ndarray | None = None

    @property
    def enabled(self) -> bool:
        with self._cfg_lock:
            return self._enabled and self._sender is not None

    @property
    def name(self) -> str:
        with self._cfg_lock:
            return self._name

    @property
    def frame_mode(self) -> NdiFrameMode:
        with self._cfg_lock:
            return self._frame_mode

    @property
    def last_error(self) -> str:
        with self._cfg_lock:
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
        with self._cfg_lock:
            self._stop_worker_locked()
            self._enabled = bool(enabled)
            self._name = (name or "CuePlayer").strip() or "CuePlayer"
            mode = str(frame_mode or "output_window")
            self._frame_mode = "video" if mode == "video" else "output_window"
            self._fit_mode = "fill" if fit_mode == "fill" else "fit"
            self._width = _even(width)
            self._height = _even(height)
            self._close_sender_locked()
            self._map_key = None
            if not self._enabled:
                self._last_error = ""
                return None
            if not ndi_available():
                self._enabled = False
                self._last_error = ndi_status()
                return self._last_error
            err = self._open_sender_locked()
            if err:
                return err
            self._start_worker_locked()
            return None

    def set_presentation(
        self, *, width: int, height: int, fit_mode: str = "fit"
    ) -> None:
        with self._cfg_lock:
            self._fit_mode = "fill" if fit_mode == "fill" else "fit"
            if self._frame_mode != "output_window" or not self._enabled:
                self._map_key = None
                return
            w, h = _even(width), _even(height)
            if (w, h) == (self._width, self._height):
                self._map_key = None
                return
            was = self._enabled
            self._stop_worker_locked()
            self._width = w
            self._height = h
            self._close_sender_locked()
            self._map_key = None
            self._enabled = was
            if not self._enabled:
                return
            err = self._open_sender_locked()
            if err:
                log.warning("NDI reopen after resize failed: %s", err)
                return
            self._start_worker_locked()

    def send_frame(self, frame: np.ndarray | None) -> None:
        """UI-thread entry: queue latest frame; worker does compose + NDI write."""
        if not self._enabled:
            return
        with self._pending_lock:
            if frame is None:
                self._pending_rgb = None
                self._pending_has_black = True
            else:
                rgb = np.asarray(frame)
                if rgb.ndim != 3 or rgb.shape[2] < 3:
                    return
                # Contiguous copy so decoder can reuse its buffer immediately.
                if rgb.dtype != np.uint8:
                    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
                self._pending_rgb = np.ascontiguousarray(rgb[:, :, :3])
                self._pending_has_black = False
            self._pending_seq += 1
        self._wake.set()

    def close(self) -> None:
        with self._cfg_lock:
            self._enabled = False
            self._stop_worker_locked()
            self._close_sender_locked()

    def _start_worker_locked(self) -> None:
        self._stop.clear()
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="ndi-send",
            daemon=True,
        )
        self._worker.start()

    def _stop_worker_locked(self) -> None:
        self._stop.set()
        self._wake.set()
        worker = self._worker
        self._worker = None
        if worker is not None and worker.is_alive():
            # Prefer waiting out a stuck write over closing the sender under it
            # (native NDI teardown while write_video_async runs can hard-crash).
            worker.join(timeout=5.0)
            if worker.is_alive():
                log.warning("NDI worker did not stop within 5s; closing sender anyway")

    def _worker_loop(self) -> None:
        last_seq = -1
        while not self._stop.is_set():
            self._wake.wait(timeout=0.05)
            self._wake.clear()
            if self._stop.is_set():
                break
            with self._pending_lock:
                seq = self._pending_seq
                if seq == last_seq:
                    continue
                rgb = self._pending_rgb
                is_black = self._pending_has_black and rgb is None
                # Take ownership of the array reference.
                self._pending_rgb = None
                last_seq = seq
            try:
                self._send_one(rgb, black=is_black)
            except Exception as exc:  # noqa: BLE001
                with self._cfg_lock:
                    self._send_failures += 1
                    if self._send_failures <= 3 or self._send_failures % 120 == 0:
                        log.warning("NDI send_frame failed: %s", exc)
                        self._last_error = f"NDI send failed: {exc}"

    def _send_one(self, rgb: np.ndarray | None, *, black: bool) -> None:
        with self._cfg_lock:
            if not self._enabled or self._sender is None:
                return
            width = self._width
            height = self._height
            frame_mode = self._frame_mode
            fit_mode = self._fit_mode
            sender = self._sender
            frame_obj = self._frame

            if rgb is None or black:
                if self._canvas_rgb is None or self._canvas_rgb.shape[:2] != (
                    height,
                    width,
                ):
                    self._canvas_rgb = np.zeros((height, width, 3), dtype=np.uint8)
                else:
                    self._canvas_rgb.fill(0)
                canvas = self._canvas_rgb
            elif frame_mode == "video":
                h, w = int(rgb.shape[0]), int(rgb.shape[1])
                w, h = _even(w), _even(h)
                if (w, h) != (width, height):
                    self._width = w
                    self._height = h
                    self._close_sender_locked()
                    err = self._open_sender_locked()
                    if err or self._sender is None:
                        return
                    sender = self._sender
                    frame_obj = self._frame
                    width, height = w, h
                if self._canvas_rgb is None or self._canvas_rgb.shape[:2] != (
                    height,
                    width,
                ):
                    self._canvas_rgb = np.zeros((height, width, 3), dtype=np.uint8)
                else:
                    self._canvas_rgb.fill(0)
                ch = min(height, rgb.shape[0])
                cw = min(width, rgb.shape[1])
                self._canvas_rgb[:ch, :cw] = rgb[:ch, :cw]
                canvas = self._canvas_rgb
            else:
                if self._canvas_rgb is None or self._canvas_rgb.shape[:2] != (
                    height,
                    width,
                ):
                    self._canvas_rgb = np.zeros((height, width, 3), dtype=np.uint8)
                if rgb.shape[0] == height and rgb.shape[1] == width:
                    np.copyto(self._canvas_rgb, rgb)
                else:
                    key = (rgb.shape[0], rgb.shape[1], width, height, fit_mode)
                    if key != self._map_key:
                        (
                            self._map_y,
                            self._map_x,
                            self._map_y0,
                            self._map_x0,
                            self._map_nh,
                            self._map_nw,
                        ) = _build_fit_maps(
                            rgb.shape[0],
                            rgb.shape[1],
                            width,
                            height,
                            fit_mode=fit_mode,
                        )
                        self._map_key = key
                    self._canvas_rgb.fill(0)
                    scaled = rgb[self._map_y][:, self._map_x]
                    y0, x0 = self._map_y0, self._map_x0
                    nh, nw = self._map_nh, self._map_nw
                    self._canvas_rgb[y0 : y0 + nh, x0 : x0 + nw] = scaled
                canvas = self._canvas_rgb

            dst = self._buf_a if self._use_a else self._buf_b
            if dst is None or dst.size != width * height * 4:
                return
            _pack_rgbx_into(dst, canvas)
            self._use_a = not self._use_a

            # Prefer async: NDI may keep the buffer until the next call; we
            # alternate A/B so the previous buffer stays valid.
            write_async = getattr(sender, "write_video_async", None)
            if callable(write_async):
                write_async(dst)
                return
            write = getattr(sender, "write_video", None)
            if callable(write):
                write(dst)
                return
            if frame_obj is not None:
                frame_obj.write_data(dst)
                sender.send_video_async()

    def _open_sender_locked(self) -> str | None:
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
            self._canvas_rgb = np.zeros((self._height, self._width, 3), dtype=np.uint8)
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
            self._last_error = ndi_runtime_missing_message(str(exc))
            log.warning("NDI configure failed: %s", exc)
            return self._last_error

    def _close_sender_locked(self) -> None:
        sender = self._sender
        self._sender = None
        self._frame = None
        self._buf_a = None
        self._buf_b = None
        self._canvas_rgb = None
        if sender is None:
            return
        try:
            if hasattr(sender, "close"):
                sender.close()
        except Exception:  # noqa: BLE001
            pass
