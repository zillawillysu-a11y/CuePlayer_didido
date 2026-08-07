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
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.media.audio_loader import PeakLevel
from cueplayer.media.video_audio_loader import load_video_audio

# Bump when on-disk layout changes (Converter must understand this schema).
ARTIFACT_FORMAT_VERSION = 5
# Base envelope density (bins / source-second). 15 min → 360k bins ≈ 3.2 MB.
BASE_PEAKS_PER_SECOND = 400.0
MAX_PEAK_BINS = 2_000_000
# Pyramid aggregate factors over base bins (Music-lane style zoom levels).
PYRAMID_FACTORS = (4, 16, 64, 256)
CHUNK_SECONDS = 8.0
CHUNK_YIELD_SECONDS = 0.02
CHUNK_YIELD_WHILE_PLAYING_SECONDS = 0.25
PROGRESS_GUI_COALESCE_SECONDS = 1.5
DEFAULT_AUDIO_STREAM_INDEX = 0

_CACHE_DIR = Path(
    os.environ.get(
        "CUEPLAYER_VIDEO_WAVE_CACHE",
        Path.home() / ".cache" / "cueplayer" / "video_waveforms",
    )
)

_playback_paused_builds = False
_playback_pause_lock = threading.Lock()


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
) -> int:
    if pcm.size == 0 or pcm_rate <= 0 or art.n_bins <= 0:
        return 0
    if pcm.ndim == 2:
        mono = pcm.mean(axis=1).astype(np.float32, copy=False)
        art.channels = max(art.channels, int(pcm.shape[1]))
    else:
        mono = np.asarray(pcm, dtype=np.float32)
        art.channels = max(art.channels, 1)
    if mono.size == 0:
        return 0
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
        return 0
    idx = idx[valid]
    vals = mono[valid]
    n = art.n_bins
    lo_acc = np.full(n, np.inf, dtype=np.float32)
    hi_acc = np.full(n, -np.inf, dtype=np.float32)
    np.minimum.at(lo_acc, idx, vals)
    np.maximum.at(hi_acc, idx, vals)
    touched = np.isfinite(lo_acc) & np.isfinite(hi_acc)
    if not np.any(touched):
        return 0
    newly = 0
    fresh = touched & (art.coverage == 0)
    if np.any(fresh):
        art.mins[fresh] = lo_acc[fresh]
        art.maxs[fresh] = hi_acc[fresh]
        art.coverage[fresh] = 1
        newly = int(np.count_nonzero(fresh))
    update = touched & (art.coverage != 0) & (~fresh)
    if np.any(update):
        art.mins[update] = np.minimum(art.mins[update], lo_acc[update])
        art.maxs[update] = np.maximum(art.maxs[update], hi_acc[update])
    return newly


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
    """Sequentially scan embedded audio into a bounded peak artifact."""
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
    while t < end - 1e-6:
        if _cancelled():
            if perf_diag.is_enabled():
                perf_diag.count("waveform_artifact.cancelled")
            return art
        while _paused():
            if _cancelled():
                return art
            if perf_diag.is_enabled():
                perf_diag.count("waveform_artifact.builder_yield")
            time.sleep(0.05)

        window = min(CHUNK_SECONDS, end - t)
        chunk_t0 = time.perf_counter()
        chunk = load_video_audio(
            path, start_seconds=t, max_duration_seconds=window
        )
        if perf_diag.is_enabled():
            perf_diag.record_ms(
                "waveform_artifact.av_window_ms",
                (time.perf_counter() - chunk_t0) * 1000.0,
            )
            perf_diag.count("waveform_artifact.chunks")

        if chunk is None or chunk.frames <= 0:
            _mark_silence_covered(art, t, window)
            t += window
            time.sleep(
                CHUNK_YIELD_WHILE_PLAYING_SECONDS
                if waveform_build_is_paused()
                else CHUNK_YIELD_SECONDS
            )
            if on_progress is not None:
                on_progress(art)
            continue

        _fill_chunk_peaks(
            art,
            pcm=chunk.samples,
            pcm_rate=chunk.sample_rate,
            pcm_origin=float(chunk.origin_seconds),
        )
        decoded_span = chunk.frames / float(chunk.sample_rate)
        t = float(chunk.origin_seconds) + decoded_span
        if t <= float(chunk.origin_seconds) + 1e-3:
            t = float(chunk.origin_seconds) + window

        if first_ready_ms is None and art.coverage_ratio > 0:
            first_ready_ms = (time.perf_counter() - t0_wall) * 1000.0
            if perf_diag.is_enabled():
                perf_diag.note(
                    "waveform_artifact.first_peaks_ready_ms", first_ready_ms
                )

        if on_progress is not None:
            on_progress(art)

        time.sleep(
            CHUNK_YIELD_WHILE_PLAYING_SECONDS
            if waveform_build_is_paused()
            else CHUNK_YIELD_SECONDS
        )
        if perf_diag.is_enabled():
            perf_diag.count("waveform_artifact.builder_yield")

    art.complete = True
    art.rebuild_pyramid()
    if perf_diag.is_enabled():
        perf_diag.count("waveform_artifact.job_completed")
        perf_diag.note(
            "waveform_artifact.complete_ms",
            (time.perf_counter() - t0_wall) * 1000.0,
        )
        perf_diag.note("waveform_artifact.memory_bytes", art.memory_bytes)
    return art


@dataclass
class _JobState:
    cache_key: str
    art: VideoWaveformArtifact
    future: Future | None = None
    generation: int = 0
    listeners: list[Callable[[VideoWaveformArtifact], None]] = field(
        default_factory=list
    )


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
            job = _JobState(
                cache_key=key,
                art=art_ref,
                generation=gen,
                listeners=list(listeners),
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
                    if result.complete:
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
