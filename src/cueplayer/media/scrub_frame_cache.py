"""Background RGB frame cache for timeline scrub previews.

While the playhead is dragged, live PyAV seek/decode on the UI thread feels
like "loading video". This cache pre-decodes a sparse ladder of frames per
clip on a worker thread (own decoder — never shares the live playback
decoder). Scrub then does a nearest-frame lookup only.

Playback / mouse-up still use VideoSyncController's live decoder for
frame-accurate Preview/Clean/NDI (one decode path for the clock; this is
only a scrub assist).
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from cueplayer.domain.models import VideoClip
from cueplayer.media.video_loader import open_media_decoder

# Sparse scrub ladder — enough to feel continuous at ~12–24 Hz drag updates.
_SCRUB_FPS = 10.0
# Always downscale scrub posters; keeps RAM bounded and decode cheap.
_SCRUB_MAX_HEIGHT = 360
# Soft caps: ~36s @ 10fps per clip, or coarser step for longer clips.
_MAX_FRAMES_PER_CLIP = 360
_MAX_TOTAL_BYTES = 220 * 1024 * 1024


@dataclass(frozen=True)
class _ClipKey:
    clip_id: str
    path: str
    mtime_ns: int
    source_in: float
    source_span: float


@dataclass
class _ClipFrames:
    key: _ClipKey
    # Parallel arrays sorted by source seconds (seconds[i] ↔ frames[i]).
    seconds: np.ndarray  # float64, shape
    frames: list[np.ndarray]
    nbytes: int


def _mtime_ns(path: Path) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


def _clip_key(clip: VideoClip) -> _ClipKey:
    span = max(0.05, float(clip.source_span_seconds or clip.duration_seconds or 0.05))
    return _ClipKey(
        clip_id=clip.id,
        path=str(clip.path),
        mtime_ns=_mtime_ns(clip.path),
        source_in=round(float(clip.source_in_seconds), 6),
        source_span=round(span, 6),
    )


def _step_for_span(span: float) -> float:
    """Frame spacing so a clip stays under _MAX_FRAMES_PER_CLIP."""
    base = 1.0 / _SCRUB_FPS
    if span <= 0:
        return base
    needed = int(span / base) + 1
    if needed <= _MAX_FRAMES_PER_CLIP:
        return base
    return max(base, span / float(_MAX_FRAMES_PER_CLIP - 1))


def _build_clip_frames(key: _ClipKey) -> _ClipFrames | None:
    path = Path(key.path)
    if not path.is_file():
        return None
    step = _step_for_span(key.source_span)
    t0 = key.source_in
    t1 = key.source_in + key.source_span
    seconds: list[float] = []
    frames: list[np.ndarray] = []
    nbytes = 0
    decoder = None
    try:
        decoder = open_media_decoder(path, max_decode_height=_SCRUB_MAX_HEIGHT)
        t = t0
        # Inclusive end so the last source moment is represented.
        while t <= t1 + 1e-9 and len(frames) < _MAX_FRAMES_PER_CLIP:
            try:
                frame = decoder.frame_at(t)
            except Exception:
                frame = None
            if frame is not None:
                # Copy: decoder may reuse the ndarray buffer on the next call.
                rgb = np.array(frame, copy=True, dtype=np.uint8)
                seconds.append(float(t))
                frames.append(rgb)
                nbytes += int(rgb.nbytes)
            t += step
    except Exception:
        return None
    finally:
        if decoder is not None:
            try:
                decoder.close()
            except Exception:
                pass
    if not frames:
        return None
    return _ClipFrames(
        key=key,
        seconds=np.asarray(seconds, dtype=np.float64),
        frames=frames,
        nbytes=nbytes,
    )


class ScrubFrameCache:
    """Per-clip sparse RGB posters filled on a background worker."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._clips: dict[str, _ClipFrames] = {}
        self._pending: set[str] = set()
        self._generation = 0
        self._total_bytes = 0
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scrub-vid")

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._clips.clear()
            self._pending.clear()
            self._total_bytes = 0

    def drop_clip(self, clip_id: str) -> None:
        with self._lock:
            old = self._clips.pop(clip_id, None)
            self._pending.discard(clip_id)
            if old is not None:
                self._total_bytes = max(0, self._total_bytes - old.nbytes)

    def preload(self, clips: list[VideoClip]) -> None:
        """Ensure each video clip has a scrub ladder (or a build in flight)."""
        for clip in clips:
            if clip.media_kind == "still" or clip.hidden:
                continue
            self.ensure(clip)

    def ensure(self, clip: VideoClip) -> None:
        if clip.media_kind == "still":
            return
        key = _clip_key(clip)
        with self._lock:
            existing = self._clips.get(clip.id)
            if existing is not None and existing.key == key:
                return
            if clip.id in self._pending:
                return
            # Stale entry for a re-trimmed / re-pathed clip.
            if existing is not None:
                self._total_bytes = max(0, self._total_bytes - existing.nbytes)
                self._clips.pop(clip.id, None)
            self._pending.add(clip.id)
            generation = self._generation
        self._executor.submit(self._build_async, generation, key)

    def nearest(self, clip_id: str, source_seconds: float) -> np.ndarray | None:
        """Return the closest cached RGB frame, or None if not ready."""
        with self._lock:
            entry = self._clips.get(clip_id)
            if entry is None or entry.seconds.size == 0:
                return None
            idx = int(np.searchsorted(entry.seconds, source_seconds, side="left"))
            if idx <= 0:
                return entry.frames[0]
            if idx >= entry.seconds.size:
                return entry.frames[-1]
            before = entry.seconds[idx - 1]
            after = entry.seconds[idx]
            if abs(source_seconds - before) <= abs(after - source_seconds):
                return entry.frames[idx - 1]
            return entry.frames[idx]

    def ready(self, clip_id: str) -> bool:
        with self._lock:
            return clip_id in self._clips

    def _build_async(self, generation: int, key: _ClipKey) -> None:
        built = _build_clip_frames(key)
        with self._lock:
            self._pending.discard(key.clip_id)
            if generation != self._generation:
                return
            if built is None:
                return
            # Evict other clips if over budget (keep the newly built one).
            old = self._clips.pop(key.clip_id, None)
            if old is not None:
                self._total_bytes = max(0, self._total_bytes - old.nbytes)
            while self._clips and self._total_bytes + built.nbytes > _MAX_TOTAL_BYTES:
                # Drop an arbitrary other clip (oldest insert order via dict).
                victim_id = next(iter(self._clips))
                if victim_id == key.clip_id:
                    break
                victim = self._clips.pop(victim_id)
                self._total_bytes = max(0, self._total_bytes - victim.nbytes)
            if self._total_bytes + built.nbytes > _MAX_TOTAL_BYTES:
                # Still too big alone — keep it anyway if it's the only entry;
                # otherwise skip to avoid blowing RAM on one huge clip.
                if self._clips:
                    return
            self._clips[key.clip_id] = built
            self._total_bytes += built.nbytes
