"""Video file probing and frame decoding (PyAV / FFmpeg).

This module only ever produces a frame in response to an explicit
`frame_at(seconds)` request from the playback layer — it never runs its
own timer. The audio sample clock stays the sole source of truth (see
`cueplayer.playback.video_sync.VideoSyncController`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cueplayer.media.av_lock import av_path_lock

import av
import numpy as np


@dataclass
class VideoInfo:
    duration_seconds: float
    width: int
    height: int
    fps: float
    media_kind: str = "video"


STILL_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})


def is_still_image_path(path: Path) -> bool:
    return Path(path).suffix.lower() in STILL_IMAGE_SUFFIXES


def probe_video(path: Path) -> VideoInfo:
    """Open + close a container just to read duration / geometry / fps."""
    return _probe_container(path, media_kind="video")


def probe_still_image(path: Path) -> VideoInfo:
    """Read geometry for a still image (no meaningful duration)."""
    return _probe_container(path, media_kind="still")


def probe_media(path: Path) -> VideoInfo:
    """Probe either a video file or a still image on the video track."""
    path = Path(path)
    if is_still_image_path(path):
        return probe_still_image(path)
    return probe_video(path)


def _probe_container(path: Path, *, media_kind: str) -> VideoInfo:
    path = Path(path)
    with av_path_lock(path):
        container = av.open(str(path))
        try:
            stream = next((s for s in container.streams if s.type == "video"), None)
            if stream is None:
                raise ValueError(f"No video stream found in {path.name}")
            duration = 0.0
            if stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
            elif container.duration is not None:
                duration = float(container.duration) / 1_000_000.0
            fps = float(stream.average_rate) if stream.average_rate else 25.0
            width = int(stream.codec_context.width)
            height = int(stream.codec_context.height)
            return VideoInfo(
                duration_seconds=max(0.0, duration),
                width=max(1, width),
                height=max(1, height),
                fps=fps if fps > 0 else 25.0,
                media_kind=media_kind,
            )
        finally:
            container.close()


class VideoDecoder:
    """
    Frame-holding decoder for one video file, optimized for the common
    "playhead moving forward" access pattern (scrubbing / playback).

    `frame_at(seconds)` returns the most recently decoded frame at or
    before the requested time, re-seeking only on backward jumps or large
    forward jumps (e.g. a Seek on the timeline).
    """

    # Re-seek instead of paying for a long sequential decode past this gap.
    _MAX_FORWARD_SKIP_SECONDS = 2.0

    def __init__(self, path: Path, *, max_decode_height: int | None = None) -> None:
        self._path = Path(path)
        # Optional decode-time downscale cap (see VideoDecodeQuality /
        # VideoSyncController.set_decode_quality). Never upscales; a frame
        # already at or below this height is returned untouched.
        self._max_decode_height = int(max_decode_height) if max_decode_height else None
        with av_path_lock(self._path):
            self._container = av.open(str(self._path))
            self._stream = next((s for s in self._container.streams if s.type == "video"), None)
            if self._stream is None:
                self._container.close()
                raise ValueError(f"No video stream found in {self._path.name}")
            self._stream.thread_type = "AUTO"
            self._time_base = float(self._stream.time_base) if self._stream.time_base else 0.0
            self._iterator = self._container.decode(self._stream)
        self._last_frame = None
        self._last_pts_seconds: float | None = None
        self._pending_frame = None
        self._pending_pts_seconds: float | None = None
        self._closed = False
        # frame_at() is called on (roughly) every AudioEngine.position_changed
        # tick — up to ~60Hz during playback — but the active *source* frame
        # only actually changes at the clip's own frame rate (typically
        # 24-30Hz). Without this cache, every intervening tick would still
        # pay for a full colorspace conversion (+ downscale reformat) of the
        # exact same AVFrame it returned last time, on whichever thread calls
        # frame_at() — a large, pointless chunk of work that was starving the
        # UI thread during video playback. Identity-keyed on the AVFrame
        # object itself: cheap, and exactly right since a given AVFrame is
        # only ever converted for one candidate "current frame" at a time.
        self._cached_ndarray: np.ndarray | None = None
        self._cached_ndarray_source = None

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        if self._closed:
            return
        # Must serialize with open/seek/decode on the same path — closing a
        # container while another thread demuxes the same file hard-crashes
        # some FFmpeg builds (mid-play / song-switch freezes).
        with av_path_lock(self._path):
            if self._closed:
                return
            self._closed = True
            try:
                self._container.close()
            except Exception:
                pass
            self._iterator = iter(())
            self._last_frame = None
            self._last_pts_seconds = None
            self._pending_frame = None
            self._pending_pts_seconds = None
            self._cached_ndarray = None
            self._cached_ndarray_source = None

    def frame_at(self, seconds: float) -> np.ndarray | None:
        """RGB24 (H, W, 3) array for the frame active at `seconds`, or None."""
        if self._closed:
            return None
        seconds = max(0.0, float(seconds))

        needs_seek = self._last_pts_seconds is None or seconds < self._last_pts_seconds - 1e-6
        if not needs_seek and self._last_pts_seconds is not None:
            needs_seek = seconds - self._last_pts_seconds > self._MAX_FORWARD_SKIP_SECONDS

        with av_path_lock(self._path):
            if self._closed:
                return None
            if needs_seek:
                self._seek_unlocked(seconds)

            result = self._last_frame
            if self._pending_frame is not None and self._pending_pts_seconds is not None:
                if self._pending_pts_seconds <= seconds + 1e-4:
                    result = self._pending_frame
                    self._last_frame = result
                    self._last_pts_seconds = self._pending_pts_seconds
                    self._pending_frame = None
                    self._pending_pts_seconds = None
                else:
                    # Convert under the path lock so close() cannot tear down
                    # the container while we still hold an AVFrame.
                    return self._convert_cached(result)

            for frame in self._iterator:
                if frame.pts is None:
                    continue
                pts = float(frame.pts * self._time_base)
                if pts <= seconds + 1e-4:
                    result = frame
                    self._last_frame = frame
                    self._last_pts_seconds = pts
                    continue
                self._pending_frame = frame
                self._pending_pts_seconds = pts
                break

            return self._convert_cached(result)

    def _seek(self, seconds: float) -> None:
        with av_path_lock(self._path):
            self._seek_unlocked(seconds)

    def _seek_unlocked(self, seconds: float) -> None:
        offset = int(seconds / self._time_base) if self._time_base else 0
        try:
            self._container.seek(offset, stream=self._stream, any_frame=False, backward=True)
        except Exception:
            pass
        self._iterator = self._container.decode(self._stream)
        self._last_frame = None
        self._last_pts_seconds = None
        self._pending_frame = None
        self._pending_pts_seconds = None
        self._cached_ndarray = None
        self._cached_ndarray_source = None

    def _convert_cached(self, frame) -> np.ndarray | None:
        """`_to_ndarray()`, but skipped entirely when `frame` is the exact
        AVFrame object we converted last call (see cache fields set up in
        `__init__`) — see there for why this matters."""
        if frame is None:
            return None
        if frame is self._cached_ndarray_source and self._cached_ndarray is not None:
            return self._cached_ndarray
        ndarray = self._to_ndarray(frame)
        self._cached_ndarray_source = frame
        self._cached_ndarray = ndarray
        return ndarray

    def _to_ndarray(self, frame) -> np.ndarray | None:  # noqa: ANN001
        if frame is None:
            return None
        limit = self._max_decode_height
        if limit and frame.height > limit:
            # Combine the resize + RGB conversion into a single swscale pass
            # (cheaper than to_ndarray() at full res followed by a Qt-side
            # scale) — even-dimension target for encoder/scaler friendliness.
            scale = limit / float(frame.height)
            width = max(2, int(round(frame.width * scale / 2.0)) * 2)
            height = max(2, int(round(limit / 2.0)) * 2)
            try:
                frame = frame.reformat(width=width, height=height, format="rgb24")
            except Exception:
                return frame.to_ndarray(format="rgb24")
        return frame.to_ndarray(format="rgb24")


class StillImageDecoder:
    """Single-frame decoder for PNG/JPG/WebP stills on the video track."""

    def __init__(self, path: Path, *, max_decode_height: int | None = None) -> None:
        self._path = Path(path)
        self._max_decode_height = int(max_decode_height) if max_decode_height else None
        self._closed = False
        self._frame: np.ndarray | None = None
        with av_path_lock(self._path):
            container = av.open(str(self._path))
            try:
                stream = next((s for s in container.streams if s.type == "video"), None)
                if stream is None:
                    raise ValueError(f"No image stream found in {self._path.name}")
                for frame in container.decode(stream):
                    self._frame = self._to_ndarray(frame)
                    break
            finally:
                container.close()
        if self._frame is None:
            raise ValueError(f"Could not decode still image {self._path.name}")

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        self._closed = True
        self._frame = None

    def frame_at(self, seconds: float) -> np.ndarray | None:  # noqa: ARG002
        if self._closed:
            return None
        return self._frame

    def _to_ndarray(self, frame) -> np.ndarray | None:  # noqa: ANN001
        if frame is None:
            return None
        limit = self._max_decode_height
        if limit and frame.height > limit:
            scale = limit / float(frame.height)
            width = max(2, int(round(frame.width * scale / 2.0)) * 2)
            height = max(2, int(round(limit / 2.0)) * 2)
            try:
                frame = frame.reformat(width=width, height=height, format="rgb24")
            except Exception:
                return frame.to_ndarray(format="rgb24")
        return frame.to_ndarray(format="rgb24")


MediaDecoder = VideoDecoder | StillImageDecoder


def open_media_decoder(path: Path, *, max_decode_height: int | None = None) -> MediaDecoder:
    if is_still_image_path(path):
        return StillImageDecoder(path, max_decode_height=max_decode_height)
    return VideoDecoder(path, max_decode_height=max_decode_height)
