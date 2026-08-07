"""Unified durable VideoWaveformArtifact for every Video with embedded audio.

One source + selected audio stream → one background build → one disk artifact.
Music-lane stand-in, Video Track lane, and Web Remote (display) all consume
this artifact. Playback PCM stays with VideoAudioMixer (untouched).

Product rules (Sprint 8):
- Continuous audio-only decode; no sparse probes; pending ≠ silence
- Never retain full-source float PCM as the waveform store
- GUI must never block waiting for construction
- Yield / pause under Play / scrub / Audio deadline pressure
- Progressive publishes coalesce; tick/paint must not decode
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.media.audio_loader import PeakLevel
from cueplayer.media.av_lock import av_path_lock

# Bump when on-disk layout changes (Converter must understand this schema).
ARTIFACT_FORMAT_VERSION = 5
# Base envelope density (bins / source-second). 15 min → 360k bins ≈ 3.2 MB.
BASE_PEAKS_PER_SECOND = 400.0
MAX_PEAK_BINS = 2_000_000
# Pyramid aggregate factors over base bins (Music-lane style zoom levels).
PYRAMID_FACTORS = (4, 16, 64, 256)
# Legacy name kept for tests that patch window sizing; sequential decoder
# uses BATCH_SECONDS between cancel/pause checks (not one open per window).
CHUNK_SECONDS = 8.0
BATCH_SECONDS = 8.0
# PyAV decoding and peak reduction both run off the GUI thread, but long
# containers can still monopolize Python/CPU if successful batches are scanned
# back-to-back. A short cooperative gap keeps Qt's event loop responsive.
CHUNK_YIELD_SECONDS = 0.035
CHUNK_YIELD_WHILE_PLAYING_SECONDS = 0.25
PROGRESS_GUI_COALESCE_SECONDS = 1.5
DEFAULT_AUDIO_STREAM_INDEX = 0

# Decode outcome kinds — never treat transient empty as confirmed silence.
DECODE_PCM = "pcm"
DECODE_SILENCE = "silence"
DECODE_EOF = "eof"
DECODE_NO_STREAM = "no_stream"
DECODE_TRANSIENT_EMPTY = "transient_empty"
DECODE_ERROR = "error"

_CACHE_DIR = Path(
    os.environ.get(
        "CUEPLAYER_VIDEO_WAVE_CACHE",
        Path.home() / ".cache" / "cueplayer" / "video_waveforms",
    )
)

_playback_paused_builds = False
_playback_pause_lock = threading.Lock()
_zoom_suppress_gui = False
_zoom_suppress_lock = threading.Lock()


def set_waveform_build_paused(paused: bool) -> None:
    """Pause/resume artifact source decode around Play / Stop."""
    global _playback_paused_builds
    with _playback_pause_lock:
        _playback_paused_builds = bool(paused)
    if perf_diag.is_enabled():
        perf_diag.note(
            "waveform_artifact.paused_for_playback", int(bool(paused))
        )
        perf_diag.count(
            "waveform_artifact.builder_pause"
            if paused
            else "waveform_artifact.builder_resume"
        )


def waveform_build_is_paused() -> bool:
    with _playback_pause_lock:
        return bool(_playback_paused_builds)


def set_waveform_gui_suppressed_for_zoom(suppressed: bool) -> None:
    """Suppress progressive GUI publishes during an active Zoom gesture."""
    global _zoom_suppress_gui
    with _zoom_suppress_lock:
        _zoom_suppress_gui = bool(suppressed)
    if perf_diag.is_enabled():
        perf_diag.count(
            "waveform_artifact.gui_suppress_zoom"
            if suppressed
            else "waveform_artifact.gui_resume_zoom"
        )


def waveform_gui_suppressed_for_zoom() -> bool:
    with _zoom_suppress_lock:
        return bool(_zoom_suppress_gui)


@dataclass
class VideoWaveformArtifact:
    """Source-time display peaks only — never playback PCM."""

    path: str
    mtime_ns: int
    size: int
    stream_index: int
    format_version: int
    peaks_per_second: float
    origin_seconds: float
    duration_seconds: float
    sample_rate: int
    channels: int
    mins: np.ndarray  # float32 base envelope
    maxs: np.ndarray  # float32 base envelope
    coverage: np.ndarray  # uint8, 1 = decoded
    # Multi-resolution levels: (samples_per_bucket_in_base_bins, mins, maxs)
    levels: list[PeakLevel] = field(default_factory=list)
    complete: bool = False
    checksum: str = ""

    @property
    def n_bins(self) -> int:
        return int(self.mins.size)

    @property
    def coverage_ratio(self) -> float:
        if self.n_bins <= 0:
            return 0.0
        return float(np.count_nonzero(self.coverage)) / float(self.n_bins)

    @property
    def decoded_duration_s(self) -> float:
        if self.n_bins <= 0 or self.peaks_per_second <= 0:
            return 0.0
        return float(np.count_nonzero(self.coverage)) / float(self.peaks_per_second)

    @property
    def memory_bytes(self) -> int:
        total = int(self.mins.nbytes + self.maxs.nbytes + self.coverage.nbytes)
        for level in self.levels:
            total += int(level.mins.nbytes + level.maxs.nbytes)
        return total

    def first_uncovered_source_time(self) -> float:
        if self.n_bins <= 0:
            return float(self.origin_seconds)
        uncovered = np.flatnonzero(self.coverage == 0)
        if uncovered.size == 0:
            return float(self.origin_seconds + self.duration_seconds)
        return float(self.origin_seconds) + float(uncovered[0]) / float(
            self.peaks_per_second
        )

    def rebuild_pyramid(self) -> None:
        """Derive multi-resolution min/max levels from the base envelope."""
        levels: list[PeakLevel] = []
        n = self.n_bins
        if n <= 0:
            self.levels = []
            return
        # Treat pending as 0 only for pyramid scaffold; paint uses coverage.
        finite_mins = np.where(self.coverage != 0, self.mins, 0.0).astype(np.float32)
        finite_maxs = np.where(self.coverage != 0, self.maxs, 0.0).astype(np.float32)
        for factor in PYRAMID_FACTORS:
            spb = int(factor)
            if spb >= n:
                continue
            buckets = max(1, n // spb)
            usable = buckets * spb
            lo = finite_mins[:usable].reshape(buckets, spb).min(axis=1)
            hi = finite_maxs[:usable].reshape(buckets, spb).max(axis=1)
            levels.append(
                PeakLevel(
                    samples_per_bucket=spb,
                    mins=lo.astype(np.float32, copy=False),
                    maxs=hi.astype(np.float32, copy=False),
                )
            )
        # Finest → coarsest ordering expected by choose_peak_level consumers
        # that walk reversed(); store coarse→fine like audio_loader.
        self.levels = sorted(levels, key=lambda lv: lv.samples_per_bucket, reverse=True)

    def compute_checksum(self) -> str:
        h = hashlib.sha256()
        h.update(self.mins.tobytes())
        h.update(self.maxs.tobytes())
        h.update(self.coverage.tobytes())
        h.update(f"{self.peaks_per_second:.6f}".encode())
        return h.hexdigest()[:32]


def artifact_bin_count(duration_seconds: float) -> int:
    dur = max(0.05, float(duration_seconds))
    n = int(np.ceil(dur * BASE_PEAKS_PER_SECOND))
    return max(1, min(MAX_PEAK_BINS, n))


def artifact_peaks_per_second_for_duration(duration_seconds: float) -> float:
    dur = max(0.05, float(duration_seconds))
    n = artifact_bin_count(dur)
    return float(n) / dur


def _stat_key(path: Path) -> tuple[str, int, int] | None:
    try:
        resolved = path.resolve()
        st = resolved.stat()
        return str(resolved), int(st.st_mtime_ns), int(st.st_size)
    except OSError:
        return None


def artifact_cache_key(
    path: Path,
    *,
    stream_index: int = DEFAULT_AUDIO_STREAM_INDEX,
    duration_seconds: float = 0.0,
) -> str | None:
    """Stable per-file key (path/mtime/size/stream/format). Duration not in key."""
    del duration_seconds
    meta = _stat_key(path)
    if meta is None:
        return None
    resolved, mtime_ns, size = meta
    raw = (
        f"{resolved}\0{mtime_ns}\0{size}\0{stream_index}\0"
        f"{ARTIFACT_FORMAT_VERSION}\0{BASE_PEAKS_PER_SECOND:.6f}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _disk_path(cache_key: str) -> Path:
    return _CACHE_DIR / f"vwave_{cache_key}.npz"


def empty_artifact(
    path: Path,
    *,
    duration_seconds: float,
    stream_index: int = DEFAULT_AUDIO_STREAM_INDEX,
    sample_rate: int = 0,
    channels: int = 0,
) -> VideoWaveformArtifact | None:
    meta = _stat_key(path)
    if meta is None:
        return None
    resolved, mtime_ns, size = meta
    n = artifact_bin_count(duration_seconds)
    pps = float(n) / max(0.05, float(duration_seconds))
    return VideoWaveformArtifact(
        path=resolved,
        mtime_ns=mtime_ns,
        size=size,
        stream_index=int(stream_index),
        format_version=ARTIFACT_FORMAT_VERSION,
        peaks_per_second=pps,
        origin_seconds=0.0,
        duration_seconds=max(0.05, float(duration_seconds)),
        sample_rate=int(sample_rate),
        channels=int(channels),
        mins=np.zeros(n, dtype=np.float32),
        maxs=np.zeros(n, dtype=np.float32),
        coverage=np.zeros(n, dtype=np.uint8),
        levels=[],
        complete=False,
        checksum="",
    )


def load_artifact_from_disk(cache_key: str) -> VideoWaveformArtifact | None:
    path = _disk_path(cache_key)
    if not path.is_file():
        if perf_diag.is_enabled():
            perf_diag.count("waveform_artifact.cache_miss")
        return None
    try:
        with np.load(path, allow_pickle=False) as data:
            if int(data["format_version"]) != ARTIFACT_FORMAT_VERSION:
                if perf_diag.is_enabled():
                    perf_diag.count("waveform_artifact.cache_corrupt")
                return None
            complete = bool(int(data["complete"]))
            if not complete:
                if perf_diag.is_enabled():
                    perf_diag.count("waveform_artifact.cache_incomplete")
                return None
            levels: list[PeakLevel] = []
            n_levels = int(data["n_levels"]) if "n_levels" in data else 0
            for i in range(n_levels):
                levels.append(
                    PeakLevel(
                        samples_per_bucket=int(data[f"level_{i}_spb"]),
                        mins=np.asarray(data[f"level_{i}_mins"], dtype=np.float32),
                        maxs=np.asarray(data[f"level_{i}_maxs"], dtype=np.float32),
                    )
                )
            art = VideoWaveformArtifact(
                path=str(data["path"]),
                mtime_ns=int(data["mtime_ns"]),
                size=int(data["size"]),
                stream_index=int(data["stream_index"]),
                format_version=int(data["format_version"]),
                peaks_per_second=float(data["peaks_per_second"]),
                origin_seconds=float(data["origin_seconds"]),
                duration_seconds=float(data["duration_seconds"]),
                sample_rate=int(data["sample_rate"]) if "sample_rate" in data else 0,
                channels=int(data["channels"]) if "channels" in data else 0,
                mins=np.asarray(data["mins"], dtype=np.float32),
                maxs=np.asarray(data["maxs"], dtype=np.float32),
                coverage=np.asarray(data["coverage"], dtype=np.uint8),
                levels=levels,
                complete=True,
                checksum=str(data["checksum"]) if "checksum" in data else "",
            )
        if art.n_bins <= 0:
            if perf_diag.is_enabled():
                perf_diag.count("waveform_artifact.cache_corrupt")
            return None
        if art.checksum:
            if art.compute_checksum() != art.checksum:
                if perf_diag.is_enabled():
                    perf_diag.count("waveform_artifact.cache_corrupt")
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                return None
        if not art.levels:
            art.rebuild_pyramid()
        if perf_diag.is_enabled():
            perf_diag.count("waveform_artifact.cache_hit")
        return art
    except Exception:
        if perf_diag.is_enabled():
            perf_diag.count("waveform_artifact.cache_corrupt")
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def save_artifact_to_disk(cache_key: str, art: VideoWaveformArtifact) -> None:
    """Atomic write of a *complete* artifact. Incomplete must never be marked complete."""
    if not art.complete:
        return
    if not art.levels:
        art.rebuild_pyramid()
    art.checksum = art.compute_checksum()
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out = _disk_path(cache_key)
        tmp = out.with_name(out.stem + ".tmp")
        arrays: dict[str, object] = {
            "path": np.asarray(art.path),
            "mtime_ns": np.int64(art.mtime_ns),
            "size": np.int64(art.size),
            "stream_index": np.int32(art.stream_index),
            "format_version": np.int32(art.format_version),
            "peaks_per_second": np.float64(art.peaks_per_second),
            "origin_seconds": np.float64(art.origin_seconds),
            "duration_seconds": np.float64(art.duration_seconds),
            "sample_rate": np.int32(art.sample_rate),
            "channels": np.int32(art.channels),
            "mins": art.mins.astype(np.float32, copy=False),
            "maxs": art.maxs.astype(np.float32, copy=False),
            "coverage": art.coverage.astype(np.uint8, copy=False),
            "complete": np.int8(1),
            "checksum": np.asarray(art.checksum),
            "n_levels": np.int32(len(art.levels)),
        }
        for i, level in enumerate(art.levels):
            arrays[f"level_{i}_spb"] = np.int32(level.samples_per_bucket)
            arrays[f"level_{i}_mins"] = level.mins.astype(np.float32, copy=False)
            arrays[f"level_{i}_maxs"] = level.maxs.astype(np.float32, copy=False)
        np.savez(str(tmp), **arrays)
        Path(str(tmp) + ".npz").replace(out)
        from cueplayer.media.cache_management import prune_media_caches

        prune_media_caches()
        if perf_diag.is_enabled():
            perf_diag.count("waveform_artifact.disk_saved")
    except Exception:
        try:
            tmp_npz = _disk_path(cache_key).with_name(
                _disk_path(cache_key).stem + ".tmp.npz"
            )
            tmp_npz.unlink(missing_ok=True)
        except OSError:
            pass


def signed_overview_from_artifact(art: VideoWaveformArtifact) -> np.ndarray:
    """Peak-hold signed mono for Music-lane display (NaN = pending)."""
    out = np.full(art.n_bins, np.nan, dtype=np.float32)
    cov = art.coverage.astype(bool)
    if not np.any(cov):
        return out
    lo = art.mins
    hi = art.maxs
    pick_hi = np.abs(hi) >= np.abs(lo)
    chosen = np.where(pick_hi, hi, lo).astype(np.float32)
    out[cov] = chosen[cov]
    return out


def _mark_silence_covered(
    art: VideoWaveformArtifact, t0: float, window: float
) -> None:
    """Cover a source range with confirmed silence (decoded zeros)."""
    pps = float(art.peaks_per_second)
    origin = float(art.origin_seconds)
    b0 = max(0, int(np.floor((t0 - origin) * pps)))
    b1 = min(art.n_bins, int(np.ceil((t0 + window - origin) * pps)))
    if b0 >= b1:
        return
    fresh = art.coverage[b0:b1] == 0
    if np.any(fresh):
        art.mins[b0:b1][fresh] = 0.0
        art.maxs[b0:b1][fresh] = 0.0
        art.coverage[b0:b1][fresh] = 1


def _fill_chunk_peaks(
    art: VideoWaveformArtifact,
    *,
    pcm: np.ndarray,
    pcm_rate: int,
    pcm_origin: float,
) -> tuple[int, int, int]:
    """Accumulate peaks into *local* bin range only.

    Returns ``(newly_covered_bins, local_bins_touched, temp_alloc_bytes)``.
    """
    if pcm.size == 0 or pcm_rate <= 0 or art.n_bins <= 0:
        return 0, 0, 0
    if pcm.ndim == 2:
        mono = pcm.mean(axis=1).astype(np.float32, copy=False)
        art.channels = max(art.channels, int(pcm.shape[1]))
    else:
        mono = np.asarray(pcm, dtype=np.float32)
        art.channels = max(art.channels, 1)
    if mono.size == 0:
        return 0, 0, 0
    art.sample_rate = int(pcm_rate) if art.sample_rate <= 0 else art.sample_rate

    pps = float(art.peaks_per_second)
    origin = float(art.origin_seconds)
    src_t0 = float(pcm_origin)
    idx = np.floor(
        (src_t0 - origin + np.arange(mono.size, dtype=np.float64) / float(pcm_rate))
        * pps
    ).astype(np.int64)
    valid = (idx >= 0) & (idx < art.n_bins)
    if not np.any(valid):
        return 0, 0, 0
    idx = idx[valid]
    vals = mono[valid]
    b_lo = int(idx.min())
    b_hi = int(idx.max()) + 1
    local_n = b_hi - b_lo
    if local_n <= 0:
        return 0, 0, 0
    local_idx = idx - b_lo
    lo_acc = np.full(local_n, np.inf, dtype=np.float32)
    hi_acc = np.full(local_n, -np.inf, dtype=np.float32)
    temp_bytes = int(lo_acc.nbytes + hi_acc.nbytes)
    np.minimum.at(lo_acc, local_idx, vals)
    np.maximum.at(hi_acc, local_idx, vals)
    touched_local = np.isfinite(lo_acc) & np.isfinite(hi_acc)
    if not np.any(touched_local):
        return 0, 0, temp_bytes
    art_lo = art.mins[b_lo:b_hi]
    art_hi = art.maxs[b_lo:b_hi]
    art_cov = art.coverage[b_lo:b_hi]
    newly = 0
    fresh = touched_local & (art_cov == 0)
    if np.any(fresh):
        art_lo[fresh] = lo_acc[fresh]
        art_hi[fresh] = hi_acc[fresh]
        art_cov[fresh] = 1
        newly = int(np.count_nonzero(fresh))
    update = touched_local & (art_cov != 0) & (~fresh)
    if np.any(update):
        art_lo[update] = np.minimum(art_lo[update], lo_acc[update])
        art_hi[update] = np.maximum(art_hi[update], hi_acc[update])
    touched = int(np.count_nonzero(touched_local))
    if perf_diag.is_enabled():
        perf_diag.note("waveform_artifact.local_bins_touched", touched)
        perf_diag.record_ms(
            "waveform_artifact.local_bins_touched_n", float(touched)
        )
        perf_diag.note("waveform_artifact.temp_alloc_bytes", temp_bytes)
        perf_diag.record_ms(
            "waveform_artifact.temp_alloc_bytes_n", float(temp_bytes)
        )
    return newly, touched, temp_bytes


@dataclass
class _DecodeBatch:
    kind: str
    samples: np.ndarray | None = None
    sample_rate: int = 0
    origin_seconds: float = 0.0
    duration_seconds: float = 0.0


class SequentialWaveformDecoder:
    """One audio-only container session; lock held only while demux is open.

    On pause / soft-yield the container is closed and ``av_path_lock`` released.
    Resume reopens and seeks to the continue cursor — not every 8 s window.
    """

    def __init__(
        self,
        path: Path,
        *,
        stream_index: int = DEFAULT_AUDIO_STREAM_INDEX,
    ) -> None:
        self.path = Path(path)
        self.stream_index = int(stream_index)
        self._lock = av_path_lock(self.path)
        self._held = False
        self._container = None
        self._stream = None
        self._resampler = None
        self._iterator = None
        self._sample_rate = 0
        self._no_stream = False
        self._eof = False
        self.open_count = 0
        self.batch_count = 0
        self._cursor_seconds = 0.0
        self._pending_seek: float | None = None

    @property
    def no_stream(self) -> bool:
        return bool(self._no_stream)

    @property
    def eof(self) -> bool:
        return bool(self._eof)

    def close(self) -> None:
        """Close demux and release ``av_path_lock`` (safe while paused)."""
        if self._container is not None:
            try:
                self._container.close()
            except Exception:
                pass
        self._container = None
        self._stream = None
        self._resampler = None
        self._iterator = None
        if self._held:
            try:
                self._lock.release()
            except RuntimeError:
                pass
            self._held = False

    def ensure_open(self, *, seek_seconds: float | None = None) -> str | None:
        """Open if needed. Returns DECODE_NO_STREAM / DECODE_ERROR or None."""
        if self._no_stream:
            return DECODE_NO_STREAM
        if self._container is not None and self._held:
            if seek_seconds is not None:
                self._seek(float(seek_seconds))
            return None
        import av

        self._lock.acquire()
        self._held = True
        try:
            self._container = av.open(str(self.path))
            self.open_count += 1
            if perf_diag.is_enabled():
                perf_diag.count("waveform_artifact.decoder_open")
                perf_diag.note(
                    "waveform_artifact.decoder_open_count", self.open_count
                )
            audio_streams = [s for s in self._container.streams if s.type == "audio"]
            if not audio_streams:
                self._no_stream = True
                self.close()
                return DECODE_NO_STREAM
            idx = max(0, min(self.stream_index, len(audio_streams) - 1))
            self._stream = audio_streams[idx]
            self._sample_rate = int(
                self._stream.codec_context.sample_rate or 48000
            )
            self._resampler = av.AudioResampler(
                format="fltp", layout="stereo", rate=self._sample_rate
            )
            target = (
                float(seek_seconds)
                if seek_seconds is not None
                else float(self._cursor_seconds)
            )
            self._seek(target)
            return None
        except Exception:
            self.close()
            return DECODE_ERROR

    def _seek(self, seconds: float) -> None:
        if self._container is None or self._stream is None:
            return
        start = max(0.0, float(seconds))
        self._cursor_seconds = start
        self._eof = False
        time_base = (
            float(self._stream.time_base)
            if self._stream.time_base
            else (1.0 / max(1, self._sample_rate))
        )
        try:
            offset = int(start / time_base) if time_base > 0 else 0
            self._container.seek(
                offset, stream=self._stream, any_frame=False, backward=True
            )
        except Exception:
            try:
                import av

                self._container.seek(int(start * av.time_base))
            except Exception:
                pass
        self._iterator = self._container.decode(self._stream)
        if self._resampler is not None:
            # Flush resampler after seek.
            try:
                list(self._resampler.resample(None))
            except Exception:
                pass

    def read_batch(self, *, max_seconds: float = BATCH_SECONDS) -> _DecodeBatch:
        """Decode up to ``max_seconds`` of PCM. Caller must have ensure_open()."""
        self.batch_count += 1
        if perf_diag.is_enabled():
            perf_diag.count("waveform_artifact.decoded_batches")
        if self._no_stream:
            return _DecodeBatch(kind=DECODE_NO_STREAM)
        if self._eof or self._container is None or self._iterator is None:
            return _DecodeBatch(kind=DECODE_EOF)
        max_dur = max(0.05, float(max_seconds))
        end_time = self._cursor_seconds + max_dur
        chunks: list[np.ndarray] = []
        collected_start: float | None = None
        sample_rate = int(self._sample_rate) or 48000
        try:
            for frame in self._iterator:
                frame_t = (
                    float(frame.pts * self._stream.time_base)
                    if frame.pts is not None and self._stream.time_base
                    else None
                )
                if frame_t is not None:
                    if frame_t + 0.05 < self._cursor_seconds:
                        continue
                    if frame_t >= end_time:
                        # Put cursor at frame_t so next batch continues here.
                        self._cursor_seconds = float(frame_t)
                        break
                    if collected_start is None:
                        collected_start = max(self._cursor_seconds, frame_t)
                for resampled in self._resampler.resample(frame):
                    arr = resampled.to_ndarray()
                    if arr.size:
                        chunks.append(arr.T.astype(np.float32, copy=False))
                if chunks:
                    got = sum(c.shape[0] for c in chunks) / float(sample_rate)
                    if got >= max_dur:
                        break
            else:
                # Iterator exhausted.
                for resampled in self._resampler.resample(None):
                    arr = resampled.to_ndarray()
                    if arr.size:
                        chunks.append(arr.T.astype(np.float32, copy=False))
                self._eof = True
        except Exception:
            return _DecodeBatch(kind=DECODE_ERROR)

        if not chunks:
            if self._eof:
                return _DecodeBatch(kind=DECODE_EOF)
            # Mid-stream empty — do not permanently cover.
            return _DecodeBatch(kind=DECODE_TRANSIENT_EMPTY)

        samples = np.concatenate(chunks, axis=0)
        max_frames = int(round(max_dur * sample_rate))
        if samples.shape[0] > max_frames:
            samples = samples[:max_frames]
        origin = collected_start if collected_start is not None else self._cursor_seconds
        dur = float(samples.shape[0]) / float(sample_rate)
        self._cursor_seconds = float(origin) + dur
        if samples.size == 0:
            return _DecodeBatch(kind=DECODE_TRANSIENT_EMPTY)
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        if peak < 1e-7:
            return _DecodeBatch(
                kind=DECODE_SILENCE,
                samples=samples,
                sample_rate=sample_rate,
                origin_seconds=float(origin),
                duration_seconds=dur,
            )
        return _DecodeBatch(
            kind=DECODE_PCM,
            samples=samples,
            sample_rate=sample_rate,
            origin_seconds=float(origin),
            duration_seconds=dur,
        )


def build_artifact_continuous(
    path: Path,
    *,
    duration_seconds: float,
    stream_index: int = DEFAULT_AUDIO_STREAM_INDEX,
    cancel_check: Callable[[], bool] | None = None,
    on_progress: Callable[[VideoWaveformArtifact], None] | None = None,
    existing: VideoWaveformArtifact | None = None,
    pause_check: Callable[[], bool] | None = None,
) -> VideoWaveformArtifact | None:
    """Sequentially scan embedded audio into a bounded peak artifact.

    Uses one decoder session (reopen only on pause / soft-yield), local-range
    peak accumulators, and distinguishes transient empty from silence.
    """
    path = Path(path)
    art = existing or empty_artifact(
        path, duration_seconds=duration_seconds, stream_index=stream_index
    )
    if art is None:
        return None

    def _cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    def _paused() -> bool:
        return bool(pause_check and pause_check()) or waveform_build_is_paused()

    t0_wall = time.perf_counter()
    first_ready_ms: float | None = None
    if perf_diag.is_enabled():
        perf_diag.count("waveform_artifact.job_started")
        perf_diag.note(
            "waveform_artifact.source_duration_s", float(art.duration_seconds)
        )
        perf_diag.count("waveform_artifact.source_decode")

    try:
        from cueplayer.util.thread_priority import lower_background_thread_priority

        lower_background_thread_priority()
    except Exception:
        pass

    end = float(art.origin_seconds) + float(art.duration_seconds)
    t = art.first_uncovered_source_time()
    decoder = SequentialWaveformDecoder(path, stream_index=stream_index)
    transient_streak = 0
    try:
        while t < end - 1e-6:
            if _cancelled():
                if perf_diag.is_enabled():
                    perf_diag.count("waveform_artifact.cancelled")
                return art
            while _paused():
                decoder.close()
                if _cancelled():
                    return art
                if perf_diag.is_enabled():
                    perf_diag.count("waveform_artifact.builder_yield")
                time.sleep(0.05)

            # Reopen + seek only when the session is closed (pause / soft-yield /
            # first open). Never reopen every 8 s while the demux stays live.
            if not decoder._held:  # noqa: SLF001
                open_err = decoder.ensure_open(seek_seconds=t)
                if open_err == DECODE_NO_STREAM:
                    if perf_diag.is_enabled():
                        perf_diag.count("waveform_artifact.no_audio_stream")
                    return None
                if open_err == DECODE_ERROR:
                    if perf_diag.is_enabled():
                        perf_diag.count("waveform_artifact.decode_error")
                    time.sleep(CHUNK_YIELD_SECONDS)
                    continue

            chunk_t0 = time.perf_counter()
            batch = decoder.read_batch(max_seconds=BATCH_SECONDS)
            if perf_diag.is_enabled():
                perf_diag.record_ms(
                    "waveform_artifact.av_window_ms",
                    (time.perf_counter() - chunk_t0) * 1000.0,
                )
                perf_diag.count("waveform_artifact.chunks")

            if batch.kind == DECODE_NO_STREAM:
                return None
            if batch.kind == DECODE_EOF:
                break
            if batch.kind == DECODE_TRANSIENT_EMPTY:
                transient_streak += 1
                if perf_diag.is_enabled():
                    perf_diag.count("waveform_artifact.transient_empty")
                # Do not mark covered. Nudge cursor slightly after repeated misses
                # so we do not spin forever on a stuck demux position.
                if transient_streak >= 8:
                    t = min(end, t + BATCH_SECONDS)
                    transient_streak = 0
                    decoder.close()
                time.sleep(CHUNK_YIELD_SECONDS)
                continue
            if batch.kind == DECODE_ERROR:
                if perf_diag.is_enabled():
                    perf_diag.count("waveform_artifact.decode_error")
                decoder.close()
                time.sleep(CHUNK_YIELD_SECONDS)
                continue

            transient_streak = 0
            if batch.kind == DECODE_SILENCE:
                _mark_silence_covered(
                    art, float(batch.origin_seconds), float(batch.duration_seconds)
                )
                if perf_diag.is_enabled():
                    perf_diag.count("waveform_artifact.confirmed_silence")
            elif batch.kind == DECODE_PCM and batch.samples is not None:
                _fill_chunk_peaks(
                    art,
                    pcm=batch.samples,
                    pcm_rate=batch.sample_rate,
                    pcm_origin=float(batch.origin_seconds),
                )

            t = float(batch.origin_seconds) + float(batch.duration_seconds)
            if t <= float(batch.origin_seconds) + 1e-4:
                t = float(batch.origin_seconds) + BATCH_SECONDS

            if first_ready_ms is None and art.coverage_ratio > 0:
                first_ready_ms = (time.perf_counter() - t0_wall) * 1000.0
                if perf_diag.is_enabled():
                    perf_diag.note(
                        "waveform_artifact.first_peaks_ready_ms", first_ready_ms
                    )

            if on_progress is not None:
                on_progress(art)

            # Successful PCM/silence batches must yield too. Previously only
            # error/empty paths slept, so a healthy long video was ironically
            # the path most likely to make Windows report "Not responding"
            # until the entire waveform finished.
            time.sleep(CHUNK_YIELD_SECONDS)

            # Hold the session across batches. Release lock only on pause
            # (handled at loop top) or completion — never reopen every 8 s.
            if _cancelled():
                return art
            if _paused():
                decoder.close()
                if perf_diag.is_enabled():
                    perf_diag.count("waveform_artifact.builder_yield")
                continue
    finally:
        decoder.close()
        if perf_diag.is_enabled():
            perf_diag.note(
                "waveform_artifact.decoder_open_count", int(decoder.open_count)
            )
            perf_diag.note(
                "waveform_artifact.decoded_batch_count", int(decoder.batch_count)
            )

    # Mark any trailing uncovered tip as silence only when we reached EOF with
    # a valid stream (confirmed end — not a hole mid-file).
    if decoder.eof and not decoder.no_stream:
        rem = art.coverage == 0
        if np.any(rem):
            # Only cover a short trailing tip (< 1 s worth of bins).
            uncovered = np.flatnonzero(rem)
            if uncovered.size and uncovered[0] > art.n_bins - max(
                1, int(art.peaks_per_second)
            ):
                art.mins[rem] = 0.0
                art.maxs[rem] = 0.0
                art.coverage[rem] = 1

    art.complete = True
    art.rebuild_pyramid()
    if perf_diag.is_enabled():
        perf_diag.count("waveform_artifact.job_completed")
        wall_s = max(1e-6, time.perf_counter() - t0_wall)
        perf_diag.note(
            "waveform_artifact.complete_ms",
            wall_s * 1000.0,
        )
        perf_diag.note(
            "waveform_artifact.build_throughput_src_per_wall",
            float(art.decoded_duration_s) / wall_s,
        )
        perf_diag.note("waveform_artifact.memory_bytes", art.memory_bytes)
    return art


def _use_isolated_waveform_process() -> bool:
    """Windows PyAV may retain the GIL; a thread cannot protect Qt from that."""
    return bool(
        os.name == "nt"
        and os.environ.get("CUEPLAYER_WAVEFORM_IN_PROCESS") != "1"
        and SequentialWaveformDecoder.__module__ == __name__
    )


def waveform_build_uses_isolated_process() -> bool:
    """Public policy query used by UI playback/waveform coordination."""
    return _use_isolated_waveform_process()


def _build_artifact_isolated(
    path: Path,
    *,
    duration_seconds: float,
    stream_index: int,
    cancel_check: Callable[[], bool] | None,
    pause_check: Callable[[], bool] | None,
    on_percent: Callable[[int], None] | None = None,
) -> VideoWaveformArtifact | None:
    """Decode in another interpreter so PyAV cannot starve Qt's GIL."""
    key = artifact_cache_key(
        path, stream_index=stream_index, duration_seconds=duration_seconds
    )
    if key is None:
        return None
    env = os.environ.copy()
    env["CUEPLAYER_WAVEFORM_IN_PROCESS"] = "1"
    env.pop("CUEPLAYER_PERF", None)
    progress_path = _disk_path(key).with_suffix(".progress")
    try:
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.unlink(missing_ok=True)
    except OSError:
        pass
    command = [
        sys.executable,
        "-m",
        "cueplayer.media.video_waveform_worker",
        str(path),
        repr(float(duration_seconds)),
        str(int(stream_index)),
        str(progress_path),
    ]
    kwargs: dict[str, object] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": env,
    }
    if os.name == "nt":
        kwargs["creationflags"] = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        proc = subprocess.Popen(command, **kwargs)  # noqa: S603
    except OSError:
        return None
    try:
        last_percent = -1
        while proc.poll() is None:
            cancelled = bool(cancel_check and cancel_check())
            # This process has its own GIL and a lowered worker priority. Keep
            # scanning while CuePlayer plays so the waveform can appear live.
            # Only cancellation (song/project change) should terminate it.
            if cancelled:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return None
            try:
                percent = max(0, min(99, int(progress_path.read_text(encoding="ascii"))))
            except (OSError, ValueError):
                percent = last_percent
            if percent >= 0 and percent != last_percent:
                last_percent = percent
                if on_percent is not None:
                    on_percent(percent)
            time.sleep(0.05)
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        return None
    if on_percent is not None:
        on_percent(100)
    try:
        progress_path.unlink(missing_ok=True)
    except OSError:
        pass
    return load_artifact_from_disk(key)


@dataclass
class _JobState:
    cache_key: str
    art: VideoWaveformArtifact
    future: Future | None = None
    generation: int = 0
    listeners: list[Callable[[VideoWaveformArtifact], None]] = field(
        default_factory=list
    )
    percent_listeners: list[Callable[[int], None]] = field(default_factory=list)


class VideoWaveformArtifactStore:
    """Process-wide in-memory + disk store; one build per media key.

    GUI-safe API never blocks waiting for construction.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_key: dict[str, VideoWaveformArtifact] = {}
        self._jobs: dict[str, _JobState] = {}
        self._generation = 0
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="vid-wave-art"
        )
        self._progress_coalesce_s = PROGRESS_GUI_COALESCE_SECONDS
        self._last_progress_emit: dict[str, float] = {}

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._by_key.clear()
            self._jobs.clear()
            self._last_progress_emit.clear()

    def peek(self, cache_key: str | None) -> VideoWaveformArtifact | None:
        if not cache_key:
            return None
        with self._lock:
            return self._by_key.get(cache_key)

    def get_or_load_disk(
        self,
        path: Path,
        *,
        duration_seconds: float,
        stream_index: int = DEFAULT_AUDIO_STREAM_INDEX,
    ) -> VideoWaveformArtifact | None:
        key = artifact_cache_key(
            path, stream_index=stream_index, duration_seconds=duration_seconds
        )
        if key is None:
            return None
        need = float(duration_seconds)

        def _usable(art: VideoWaveformArtifact | None) -> VideoWaveformArtifact | None:
            if art is None:
                return None
            if float(art.duration_seconds) + 0.5 < need and not art.complete:
                return None
            if art.complete and float(art.duration_seconds) + 0.5 < need:
                return None
            return art

        with self._lock:
            hit = _usable(self._by_key.get(key))
            if hit is not None and hit.complete:
                if perf_diag.is_enabled():
                    perf_diag.count("waveform_artifact.cache_hit")
                return hit
            # Partial in-RAM is OK for progressive paint.
            partial = self._by_key.get(key)
            if partial is not None and partial.coverage_ratio > 0:
                return partial
        disk = load_artifact_from_disk(key)
        if disk is not None:
            with self._lock:
                self._by_key[key] = disk
            return disk
        return None

    def ensure_building(
        self,
        path: Path,
        *,
        duration_seconds: float,
        stream_index: int = DEFAULT_AUDIO_STREAM_INDEX,
        cancel_check: Callable[[], bool] | None = None,
        pause_check: Callable[[], bool] | None = None,
        on_update: Callable[[VideoWaveformArtifact], None] | None = None,
        on_percent: Callable[[int], None] | None = None,
    ) -> VideoWaveformArtifact | None:
        """Hydrate disk / return partial / start single-flight build. Never waits."""
        key = artifact_cache_key(
            path, stream_index=stream_index, duration_seconds=duration_seconds
        )
        if key is None:
            return None
        existing = self.get_or_load_disk(
            path, duration_seconds=duration_seconds, stream_index=stream_index
        )
        if existing is not None and existing.complete:
            if on_update is not None:
                on_update(existing)
            return existing

        with self._lock:
            gen = self._generation
            job = self._jobs.get(key)
            if job is not None and job.future is not None and not job.future.done():
                if on_update is not None:
                    job.listeners.append(on_update)
                if on_percent is not None:
                    job.percent_listeners.append(on_percent)
                if perf_diag.is_enabled():
                    perf_diag.count("waveform_artifact.job_deduplicated")
                return job.art

            art_ref = existing or empty_artifact(
                path,
                duration_seconds=duration_seconds,
                stream_index=stream_index,
            )
            if art_ref is None:
                return None
            self._by_key[key] = art_ref
            listeners = [on_update] if on_update is not None else []
            percent_listeners = [on_percent] if on_percent is not None else []
            job = _JobState(
                cache_key=key,
                art=art_ref,
                generation=gen,
                listeners=list(listeners),
                percent_listeners=list(percent_listeners),
            )
            self._jobs[key] = job

            def _run() -> VideoWaveformArtifact | None:
                def _progress(a: VideoWaveformArtifact) -> None:
                    now = time.monotonic()
                    with self._lock:
                        if gen != self._generation:
                            return
                        self._by_key[key] = a
                        last = self._last_progress_emit.get(key, 0.0)
                        if (
                            not a.complete
                            and now - last < self._progress_coalesce_s
                            and last > 0.0
                        ):
                            if perf_diag.is_enabled():
                                perf_diag.count(
                                    "waveform_artifact.progressive_coalesced"
                                )
                            return
                        if not a.complete and waveform_gui_suppressed_for_zoom():
                            if perf_diag.is_enabled():
                                perf_diag.count(
                                    "waveform_artifact.gui_notify_suppressed_zoom"
                                )
                            return
                        self._last_progress_emit[key] = now
                        cbs = list(job.listeners)
                    if perf_diag.is_enabled():
                        perf_diag.count("waveform_artifact.progressive_publish")
                        if a.complete:
                            perf_diag.count("waveform_artifact.final_publish")
                    for cb in cbs:
                        try:
                            cb(a)
                        except Exception:
                            pass

                def _cancel() -> bool:
                    if gen != self._generation:
                        return True
                    return bool(cancel_check and cancel_check())

                def _percent(pct: int) -> None:
                    with self._lock:
                        cbs = list(job.percent_listeners)
                    for cb in cbs:
                        try:
                            cb(int(pct))
                        except Exception:
                            pass

                isolated = _use_isolated_waveform_process()
                if isolated:
                    if perf_diag.is_enabled():
                        perf_diag.count("waveform_artifact.isolated_process")
                    result = _build_artifact_isolated(
                        path,
                        duration_seconds=duration_seconds,
                        stream_index=stream_index,
                        cancel_check=_cancel,
                        pause_check=pause_check,
                        on_percent=_percent,
                    )
                else:
                    result = build_artifact_continuous(
                        path,
                        duration_seconds=duration_seconds,
                        stream_index=stream_index,
                        cancel_check=_cancel,
                        pause_check=pause_check,
                        on_progress=_progress,
                        existing=art_ref,
                    )
                if result is None:
                    return None
                with self._lock:
                    if gen != self._generation:
                        return result
                    self._by_key[key] = result
                    if result.complete and not isolated:
                        save_artifact_to_disk(key, result)
                    cbs = list(job.listeners)
                    self._jobs.pop(key, None)
                for cb in cbs:
                    try:
                        cb(result)
                    except Exception:
                        pass
                return result

            job.future = self._executor.submit(_run)
            return art_ref

    def wait_in_worker(
        self,
        path: Path,
        *,
        duration_seconds: float,
        stream_index: int = DEFAULT_AUDIO_STREAM_INDEX,
        cancel_check: Callable[[], bool] | None = None,
        pause_check: Callable[[], bool] | None = None,
        on_update: Callable[[VideoWaveformArtifact], None] | None = None,
        on_percent: Callable[[int], None] | None = None,
        timeout: float = 3600.0,
    ) -> VideoWaveformArtifact | None:
        """Background-thread wait for completion. NEVER call from GUI thread."""
        art = self.ensure_building(
            path,
            duration_seconds=duration_seconds,
            stream_index=stream_index,
            cancel_check=cancel_check,
            pause_check=pause_check,
            on_update=on_update,
            on_percent=on_percent,
        )
        if art is not None and art.complete:
            return art
        key = artifact_cache_key(
            path, stream_index=stream_index, duration_seconds=duration_seconds
        )
        if key is None:
            return art
        with self._lock:
            job = self._jobs.get(key)
            fut = job.future if job is not None else None
        if fut is None:
            return self.peek(key) or art
        try:
            return fut.result(timeout=timeout)
        except Exception:
            with self._lock:
                return self._by_key.get(key) or art


# Module singleton — all waveform-display consumers share one builder.
_STORE: VideoWaveformArtifactStore | None = None
_STORE_LOCK = threading.Lock()


def artifact_store() -> VideoWaveformArtifactStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = VideoWaveformArtifactStore()
        return _STORE


# Back-compat aliases used by older call sites / tests during migration.
EmbeddedWaveformArtifact = VideoWaveformArtifact
EmbeddedWaveformArtifactStore = VideoWaveformArtifactStore
PEAKS_PER_SECOND = BASE_PEAKS_PER_SECOND


def build_or_wait(
    path: Path,
    *,
    duration_seconds: float,
    stream_index: int = DEFAULT_AUDIO_STREAM_INDEX,
    cancel_check: Callable[[], bool] | None = None,
    pause_check: Callable[[], bool] | None = None,
    on_update: Callable[[VideoWaveformArtifact], None] | None = None,
) -> VideoWaveformArtifact | None:
    """Deprecated name — worker-only wait. Prefer ``ensure_building`` on GUI."""
    return artifact_store().wait_in_worker(
        path,
        duration_seconds=duration_seconds,
        stream_index=stream_index,
        cancel_check=cancel_check,
        pause_check=pause_check,
        on_update=on_update,
    )
