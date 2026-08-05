"""Video file probing and frame decoding (PyAV / FFmpeg).

This module only ever produces a frame in response to an explicit
`frame_at(seconds)` request from the playback layer — it never runs its
own timer. The audio sample clock stays the sole source of truth (see
`cueplayer.playback.video_sync.VideoSyncController`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from cueplayer.diagnostics import perf as perf_diag
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


@dataclass
class SeekTelemetry:
    """Last seek measurement for diagnostics (Round 8 deterministic seek)."""

    requested_time: float = 0.0
    actual_time: float | None = None  # first decoded PTS after keyframe seek
    frames_to_target: int = 0
    seek_ms: float = 0.0
    decode_to_target_ms: float = 0.0
    total_ms: float = 0.0
    decoder_recreated: bool = False
    timed_out: bool = False
    eof_hit: bool = False
    time_base: float = 0.0
    reused_decoder: bool = True


# Abandon decode-forward if keyframe→target takes longer than this (GOP stalls).
_SEEK_DECODE_DEADLINE_S = 1.5
_MAX_FRAMES_TO_TARGET = 450


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
    """Decode video frames on demand. Never owns a playback clock.

    Seek policy: PyAV keyframe seek (``any_frame=False``, ``backward=True``),
    then decode forward until the first frame at or after the target.
    """

    # Re-seek instead of paying for a long sequential decode past this gap.
    _MAX_FORWARD_SKIP_SECONDS = 2.0

    def __init__(self, path: Path, *, max_decode_height: int | None = None) -> None:
        self._path = Path(path)
        self._max_decode_height = int(max_decode_height) if max_decode_height else None
        with av_path_lock(self._path):
            self._container = av.open(str(self._path))
            self._stream = next((s for s in self._container.streams if s.type == "video"), None)
            if self._stream is None:
                self._container.close()
                raise ValueError(f"No video stream found in {self._path.name}")
            self._stream.thread_type = "FRAME"
            self._time_base = float(self._stream.time_base) if self._stream.time_base else 0.0
            self._iterator = self._container.decode(self._stream)
        self._last_frame = None
        self._last_pts_seconds: float | None = None
        self._pending_frame = None
        self._pending_pts_seconds: float | None = None
        self._closed = False
        self._cached_ndarray: np.ndarray | None = None
        self._cached_ndarray_source = None
        self.last_seek = SeekTelemetry(time_base=self._time_base)
        self._seek_timed_out = False

    @property
    def path(self) -> Path:
        return self._path

    @property
    def seek_timed_out(self) -> bool:
        return bool(self._seek_timed_out)

    def close(self) -> None:
        if self._closed:
            return
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

    def frame_at(
        self,
        seconds: float,
        *,
        lock_timeout: float | None = None,
        stale_on_timeout: bool = True,
        deadline_s: float | None = None,
    ) -> np.ndarray | None:
        """RGB24 (H, W, 3) array for the frame active at `seconds`, or None.

        ``deadline_s``: max wall time for keyframe-seek + decode-forward. On
        timeout, returns best frame so far (or None) and sets ``seek_timed_out``
        so the controller can recreate the decoder.
        """
        if self._closed:
            return None
        seconds = max(0.0, float(seconds))
        self._seek_timed_out = False
        deadline = float(
            _SEEK_DECODE_DEADLINE_S if deadline_s is None else deadline_s
        )

        needs_seek = self._last_pts_seconds is None or seconds < self._last_pts_seconds - 1e-6
        if not needs_seek and self._last_pts_seconds is not None:
            needs_seek = seconds - self._last_pts_seconds > self._MAX_FORWARD_SKIP_SECONDS

        lock = av_path_lock(self._path)
        stale = self._cached_ndarray
        if lock_timeout is not None:
            got = lock.acquire(timeout=float(lock_timeout))
            if not got:
                return stale if stale_on_timeout else None
        elif stale is None:
            lock.acquire()
            got = True
        else:
            got = lock.acquire(timeout=0.08)
            if not got:
                return stale if stale_on_timeout else None
        try:
            if self._closed:
                return None
            total_t0 = monotonic()
            seek_ms = 0.0
            first_pts: float | None = None
            frames_to_target = 0
            eof_hit = False

            if needs_seek:
                if perf_diag.is_enabled():
                    from cueplayer.diagnostics import video_sm_trace as sm_trace

                    sm_trace.set_worker_runtime(
                        sm_trace.WorkerRuntime.SEEKING,
                        reason="media_decoder_seek",
                        emit_event=True,
                    )
                seek_t0 = monotonic()
                self._seek_unlocked(seconds)
                seek_ms = (monotonic() - seek_t0) * 1000.0

            if perf_diag.is_enabled():
                from cueplayer.diagnostics import video_sm_trace as sm_trace

                sm_trace.set_worker_runtime(
                    sm_trace.WorkerRuntime.DECODING,
                    reason="media_decoder_decode_loop",
                    emit_event=True,
                )

            result = self._last_frame
            decode_t0 = monotonic()
            if self._pending_frame is not None and self._pending_pts_seconds is not None:
                if self._pending_pts_seconds <= seconds + 1e-4:
                    result = self._pending_frame
                    self._last_frame = result
                    self._last_pts_seconds = self._pending_pts_seconds
                    self._pending_frame = None
                    self._pending_pts_seconds = None
                else:
                    out = self._convert_cached(result)
                    if needs_seek:
                        self._record_seek_telemetry(
                            requested=seconds,
                            actual=self._last_pts_seconds,
                            frames=0,
                            seek_ms=seek_ms,
                            decode_ms=(monotonic() - decode_t0) * 1000.0,
                            total_ms=(monotonic() - total_t0) * 1000.0,
                            timed_out=False,
                            eof_hit=False,
                        )
                    return out

            for frame in self._iterator:
                if frame.pts is None:
                    continue
                pts = float(frame.pts * self._time_base)
                frames_to_target += 1
                if first_pts is None:
                    first_pts = pts
                if pts <= seconds + 1e-4:
                    result = frame
                    self._last_frame = frame
                    self._last_pts_seconds = pts
                    if (monotonic() - total_t0) > deadline:
                        self._seek_timed_out = True
                        break
                    if frames_to_target >= _MAX_FRAMES_TO_TARGET:
                        self._seek_timed_out = True
                        break
                    continue
                self._pending_frame = frame
                self._pending_pts_seconds = pts
                break
            else:
                eof_hit = True
                if needs_seek and result is None:
                    self._seek_timed_out = True

            if needs_seek or self._seek_timed_out:
                self._record_seek_telemetry(
                    requested=seconds,
                    actual=first_pts if first_pts is not None else self._last_pts_seconds,
                    frames=frames_to_target,
                    seek_ms=seek_ms,
                    decode_ms=(monotonic() - decode_t0) * 1000.0,
                    total_ms=(monotonic() - total_t0) * 1000.0,
                    timed_out=bool(self._seek_timed_out),
                    eof_hit=eof_hit,
                )

            return self._convert_cached(result)
        finally:
            lock.release()

    def _record_seek_telemetry(
        self,
        *,
        requested: float,
        actual: float | None,
        frames: int,
        seek_ms: float,
        decode_ms: float,
        total_ms: float,
        timed_out: bool,
        eof_hit: bool,
    ) -> None:
        self.last_seek = SeekTelemetry(
            requested_time=float(requested),
            actual_time=float(actual) if actual is not None else None,
            frames_to_target=int(frames),
            seek_ms=float(seek_ms),
            decode_to_target_ms=float(decode_ms),
            total_ms=float(total_ms),
            decoder_recreated=False,
            timed_out=bool(timed_out),
            eof_hit=bool(eof_hit),
            time_base=float(self._time_base),
            reused_decoder=True,
        )
        if not perf_diag.is_enabled():
            return
        perf_diag.note("video.seek.requested_time", requested)
        if actual is not None:
            perf_diag.note("video.seek.actual_time", actual)
            perf_diag.note("video.seek.keyframe_pts", actual)
            # First decoded PTS after keyframe seek ≈ keyframe position.
            # Distance to target estimates how far we decode-forward (GOP depth).
            distance = max(0.0, float(requested) - float(actual))
            perf_diag.note("video.seek.keyframe_distance_s", round(distance, 4))
        perf_diag.note("video.seek.frames_to_target", frames)
        # frames_to_target counts decode-forward from keyframe through target.
        # At ~30 fps, 88 frames ≈ 2.9 s GOP — expected for long-GOP H.264.
        perf_diag.note("video.seek.gop_frames_estimate", frames)
        perf_diag.record_ms("video.seek.total_ms", total_ms)
        perf_diag.record_ms("video.seek.decode_to_target_ms", decode_ms)
        perf_diag.record_ms("video.seek.keyframe_seek_ms", seek_ms)
        if timed_out:
            perf_diag.count("video.seek.deadline_timeout")
        if eof_hit:
            perf_diag.count("video.seek.eof_hit")

    def _seek(self, seconds: float) -> None:
        with av_path_lock(self._path):
            self._seek_unlocked(seconds)

    def _seek_unlocked(self, seconds: float) -> None:
        """Keyframe-aligned seek: preceding keyframe, then decode-forward."""
        offset = int(seconds / self._time_base) if self._time_base else 0
        try:
            self._container.seek(
                offset, stream=self._stream, any_frame=False, backward=True
            )
        except Exception:
            pass
        # Recreate iterator = flush decoder state after seek.
        self._iterator = self._container.decode(self._stream)
        self._last_frame = None
        self._last_pts_seconds = None
        self._pending_frame = None
        self._pending_pts_seconds = None
        self._cached_ndarray = None
        self._cached_ndarray_source = None

    def _convert_cached(self, frame) -> np.ndarray | None:
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
        self.last_seek = SeekTelemetry()
        self._seek_timed_out = False
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

    @property
    def seek_timed_out(self) -> bool:
        return False

    def close(self) -> None:
        self._closed = True
        self._frame = None

    def frame_at(
        self,
        seconds: float,
        *,
        lock_timeout: float | None = None,
        stale_on_timeout: bool = True,
        deadline_s: float | None = None,
    ) -> np.ndarray | None:  # noqa: ARG002
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
