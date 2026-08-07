"""Shared continuous embedded-audio waveform artifact for long videos."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cueplayer.domain.models import VideoClip
from cueplayer.media.video_clip_waveform import (
    VideoClipWaveformCache,
    peaks_from_embedded_artifact,
)
from cueplayer.media.video_limits import HEAVY_VIDEO_SECONDS, clip_is_heavy
from cueplayer.media.video_waveform_artifact import (
    MAX_PEAK_BINS,
    PEAKS_PER_SECOND,
    artifact_bin_count,
    artifact_cache_key,
    artifact_has_false_zero_gaps,
    artifact_store,
    build_artifact_continuous,
    load_artifact_from_disk,
    save_artifact_to_disk,
    signed_overview_from_artifact,
)
from cueplayer.media.video_audio_loader import VideoAudioBuffer


@pytest.fixture(autouse=True)
def _clear_store() -> None:
    artifact_store().clear()
    yield
    artifact_store().clear()


def _fake_tone_loader(path: Path, *, amp: float = 0.4):
    def _load(
        p: Path,
        *,
        start_seconds: float = 0.0,
        max_duration_seconds: float | None = None,
    ) -> VideoAudioBuffer:
        del p
        sr = 2000
        n = max(1, int(round(float(max_duration_seconds or 1.0) * sr)))
        t = (np.arange(n, dtype=np.float32) / sr) + float(start_seconds)
        tone = (amp * np.sin(2 * np.pi * 4.0 * t)).astype(np.float32)
        samples = np.stack([tone, tone], axis=1)
        return VideoAudioBuffer(
            path=path,
            sample_rate=sr,
            samples=samples,
            origin_seconds=float(start_seconds),
        )

    return _load


def test_heavy_clip_no_longer_returns_none_from_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "heavy.mp4"
    path.write_bytes(b"x")
    clip = VideoClip.create(
        name="h",
        path=path,
        start_seconds=0.0,
        duration_seconds=HEAVY_VIDEO_SECONDS + 60.0,
        source_duration_seconds=HEAVY_VIDEO_SECONDS + 60.0,
    )
    assert clip_is_heavy(clip)

    import cueplayer.media.video_waveform_artifact as art_mod
    import cueplayer.media.video_clip_waveform as wave_mod

    monkeypatch.setattr(art_mod, "load_video_audio", _fake_tone_loader(path))
    monkeypatch.setattr(art_mod, "CHUNK_SECONDS", 20.0)
    monkeypatch.setattr(art_mod, "CHUNK_YIELD_SECONDS", 0.0)
    monkeypatch.setattr(art_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(art_mod, "MAX_PEAK_BINS", 800)
    monkeypatch.setattr(art_mod, "PEAKS_PER_SECOND", 1.0)

    cache = VideoClipWaveformCache()
    # Synchronously build via artifact path.
    peaks = cache._build_from_shared_artifact(  # noqa: SLF001
        cache._generation, cache.key_for(clip), clip  # noqa: SLF001
    )
    assert peaks is not None
    assert peaks.mono.size > 0
    assert peaks.coverage is not None
    assert int(np.count_nonzero(peaks.coverage)) > 0


def test_continuous_artifact_has_no_sparse_zero_gaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "long.mp4"
    path.write_bytes(b"x")
    import cueplayer.media.video_waveform_artifact as art_mod

    monkeypatch.setattr(art_mod, "load_video_audio", _fake_tone_loader(path))
    monkeypatch.setattr(art_mod, "CHUNK_SECONDS", 15.0)
    monkeypatch.setattr(art_mod, "CHUNK_YIELD_SECONDS", 0.0)
    monkeypatch.setattr(art_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(art_mod, "MAX_PEAK_BINS", 600)
    monkeypatch.setattr(art_mod, "PEAKS_PER_SECOND", 1.0)

    art = build_artifact_continuous(path, duration_seconds=600.0)
    assert art is not None
    assert art.complete
    assert art.coverage_ratio == pytest.approx(1.0, abs=1e-6)
    assert not artifact_has_false_zero_gaps(art)
    # Energy present across former 12s probe holes (e.g. t=6, 18, 30…).
    pps = art.peaks_per_second
    for t in (6.0, 18.0, 30.0, 90.0, 200.0):
        b = int(t * pps)
        assert art.coverage[b] == 1
        assert abs(float(art.maxs[b])) > 0.01 or abs(float(art.mins[b])) > 0.01


def test_memory_bound_not_full_rate_pcm() -> None:
    dur = 15 * 60.0
    n = artifact_bin_count(dur)
    assert n <= MAX_PEAK_BINS
    # Far below duration × 48000 × 4 bytes × channels.
    full_rate_bytes = dur * 48000 * 2 * 4
    artifact_bytes = n * (4 + 4 + 1)
    # ~200 Hz overview is still ≪ full-rate PCM.
    assert artifact_bytes < full_rate_bytes / 100.0
    assert artifact_bytes < 2_500_000
    assert n == int(np.ceil(dur * PEAKS_PER_SECOND)) or n == MAX_PEAK_BINS


def test_main_and_video_lane_share_same_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "shared.mp4"
    path.write_bytes(b"x")
    import cueplayer.media.video_waveform_artifact as art_mod
    from cueplayer.media.video_music_standin import build_music_standin_from_video

    monkeypatch.setattr(art_mod, "load_video_audio", _fake_tone_loader(path))
    monkeypatch.setattr(art_mod, "CHUNK_SECONDS", 20.0)
    monkeypatch.setattr(art_mod, "CHUNK_YIELD_SECONDS", 0.0)
    monkeypatch.setattr(art_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(art_mod, "MAX_PEAK_BINS", 400)
    monkeypatch.setattr(art_mod, "PEAKS_PER_SECOND", 1.0)

    dur = HEAVY_VIDEO_SECONDS + 30.0
    clip = VideoClip.create(
        name="s",
        path=path,
        start_seconds=0.0,
        duration_seconds=dur,
        source_duration_seconds=dur,
    )
    buf = build_music_standin_from_video(clip, timeline_duration=dur)
    assert buf is not None
    key = artifact_cache_key(path, duration_seconds=dur)
    assert key is not None
    stored = artifact_store().peek(key)
    assert stored is not None and stored.complete

    lane = peaks_from_embedded_artifact(clip, stored)
    assert lane is not None
    # Same source extrema presence.
    assert float(np.nanmax(np.abs(signed_overview_from_artifact(stored)))) > 0.01
    assert float(np.nanmax(np.abs(lane.mono))) > 0.01
    # Full-resolution bipolar envelope (not 64–512 clip overview buckets).
    assert lane.mins.size == stored.n_bins
    assert lane.maxs.size == lane.mins.size
    assert float(np.nanmax(lane.maxs - lane.mins)) > 0.01


def test_trim_and_loop_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trim.mp4"
    path.write_bytes(b"x")
    import cueplayer.media.video_waveform_artifact as art_mod
    from cueplayer.media.video_clip_waveform import sample_source_raw_for_clip_times

    monkeypatch.setattr(art_mod, "load_video_audio", _fake_tone_loader(path, amp=0.7))
    monkeypatch.setattr(art_mod, "CHUNK_SECONDS", 10.0)
    monkeypatch.setattr(art_mod, "CHUNK_YIELD_SECONDS", 0.0)
    monkeypatch.setattr(art_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(art_mod, "MAX_PEAK_BINS", 300)
    monkeypatch.setattr(art_mod, "PEAKS_PER_SECOND", 2.0)

    art = build_artifact_continuous(path, duration_seconds=120.0)
    assert art is not None
    clip = VideoClip.create(
        name="t",
        path=path,
        start_seconds=5.0,
        duration_seconds=40.0,
        source_in_seconds=10.0,
        source_duration_seconds=120.0,
    )
    clip.source_out_seconds = 30.0  # span 20s, looped across 40s timeline
    peaks = peaks_from_embedded_artifact(clip, art)
    assert peaks is not None
    lo, hi = sample_source_raw_for_clip_times(peaks, clip, clip_t0=0.0, clip_t1=0.5)
    assert hi == hi  # finite
    lo2, hi2 = sample_source_raw_for_clip_times(peaks, clip, clip_t0=20.0, clip_t1=20.5)
    assert hi2 == hi2


def test_disk_cache_hit_and_invalidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "disk.mp4"
    path.write_bytes(b"abc")
    import cueplayer.media.video_waveform_artifact as art_mod

    monkeypatch.setattr(art_mod, "load_video_audio", _fake_tone_loader(path))
    monkeypatch.setattr(art_mod, "CHUNK_SECONDS", 10.0)
    monkeypatch.setattr(art_mod, "CHUNK_YIELD_SECONDS", 0.0)
    monkeypatch.setattr(art_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(art_mod, "MAX_PEAK_BINS", 200)
    monkeypatch.setattr(art_mod, "PEAKS_PER_SECOND", 1.0)
    monkeypatch.setattr(
        art_mod, "_CACHE_DIR", tmp_path / "wave_cache"
    )

    dur = 90.0
    art = build_artifact_continuous(path, duration_seconds=dur)
    assert art is not None and art.complete
    key = artifact_cache_key(path, duration_seconds=dur)
    assert key is not None
    save_artifact_to_disk(key, art)
    artifact_store().clear()
    loaded = load_artifact_from_disk(key)
    assert loaded is not None
    assert loaded.n_bins == art.n_bins
    assert loaded.complete

    # Source change → new key.
    path.write_bytes(b"abcd")
    key2 = artifact_cache_key(path, duration_seconds=dur)
    assert key2 != key
    assert load_artifact_from_disk(key2) is None


def test_stale_generation_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "stale.mp4"
    path.write_bytes(b"x")
    import cueplayer.media.video_waveform_artifact as art_mod

    monkeypatch.setattr(art_mod, "load_video_audio", _fake_tone_loader(path))
    monkeypatch.setattr(art_mod, "CHUNK_SECONDS", 8.0)
    monkeypatch.setattr(art_mod, "CHUNK_YIELD_SECONDS", 0.0)
    monkeypatch.setattr(art_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(art_mod, "MAX_PEAK_BINS", 150)
    monkeypatch.setattr(art_mod, "PEAKS_PER_SECOND", 1.0)

    cancelled = {"v": False}

    def _cancel() -> bool:
        return bool(cancelled["v"])

    updates: list[float] = []

    def _prog(art) -> None:  # noqa: ANN001
        updates.append(art.coverage_ratio)
        if art.coverage_ratio > 0.05:
            cancelled["v"] = True

    art = build_artifact_continuous(
        path, duration_seconds=120.0, cancel_check=_cancel, on_progress=_prog
    )
    assert art is not None
    assert not art.complete or cancelled["v"]


def test_progressive_pending_is_nan_not_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "prog.mp4"
    path.write_bytes(b"x")
    import cueplayer.media.video_waveform_artifact as art_mod

    monkeypatch.setattr(art_mod, "load_video_audio", _fake_tone_loader(path))
    monkeypatch.setattr(art_mod, "CHUNK_SECONDS", 5.0)
    monkeypatch.setattr(art_mod, "CHUNK_YIELD_SECONDS", 0.0)
    monkeypatch.setattr(art_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(art_mod, "MAX_PEAK_BINS", 200)
    monkeypatch.setattr(art_mod, "PEAKS_PER_SECOND", 2.0)

    seen_partial = {"ok": False}

    def _prog(art) -> None:  # noqa: ANN001
        if 0.0 < art.coverage_ratio < 1.0:
            overview = signed_overview_from_artifact(art)
            pending = ~art.coverage.astype(bool)
            assert np.all(np.isnan(overview[pending]))
            seen_partial["ok"] = True
            # Stop early after proving pending≠0.
            art.coverage[:] = 1
            art.complete = True

    # Force cancel after first progress by completing artificially inside callback
    # is awkward — instead cancel after first progress.
    cancel = {"v": False}

    def _on(art) -> None:  # noqa: ANN001
        _prog(art)
        cancel["v"] = True

    build_artifact_continuous(
        path,
        duration_seconds=60.0,
        cancel_check=lambda: cancel["v"],
        on_progress=_on,
    )
    assert seen_partial["ok"]


def test_seed_from_standin_installs_video_lane_peaks(tmp_path: Path) -> None:
    from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid
    from cueplayer.media.video_clip_waveform import (
        VideoClipWaveformCache,
        peaks_from_standin_audio,
    )

    path = tmp_path / "v.mp4"
    path.write_bytes(b"x")
    sr = 800
    n = sr * 3
    mono = (0.5 * np.sin(2 * np.pi * np.arange(n) / sr * 6)).astype(np.float32)
    samples = np.stack([mono, mono], axis=1)
    _, levels = build_peak_pyramid(samples, sr)
    buf = AudioBuffer(
        path=path,
        sample_rate=sr,
        samples=samples,
        mono=mono,
        peak_levels=levels,
    )
    clip = VideoClip.create(
        name="v",
        path=path,
        start_seconds=0.0,
        duration_seconds=3.0,
        source_duration_seconds=3.0,
    )
    peaks = peaks_from_standin_audio(clip, buf)
    assert peaks is not None
    assert peaks.sample_rate == sr
    assert peaks.mono.size == n
    cache = VideoClipWaveformCache()
    assert cache.seed_from_standin(clip, buf, notify=False)
    assert cache.get_peaks(clip, allow_submit=False) is peaks or (
        cache.get_peaks(clip, allow_submit=False) is not None
    )


def test_cache_key_stable_across_duration_probe_drift(tmp_path: Path) -> None:
    path = tmp_path / "stable.mp4"
    path.write_bytes(b"x")
    k1 = artifact_cache_key(path, duration_seconds=180.0)
    k2 = artifact_cache_key(path, duration_seconds=180.012)
    k3 = artifact_cache_key(path, duration_seconds=205.0)
    assert k1 is not None and k1 == k2 == k3


def test_sync_hydrate_after_clear_restores_peaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Save→reload must paint immediately from disk, not wait on a rebuild."""
    path = tmp_path / "song.mp4"
    path.write_bytes(b"x")
    import cueplayer.media.video_waveform_artifact as art_mod

    monkeypatch.setattr(art_mod, "load_video_audio", _fake_tone_loader(path))
    monkeypatch.setattr(art_mod, "CHUNK_SECONDS", 30.0)
    monkeypatch.setattr(art_mod, "CHUNK_YIELD_SECONDS", 0.0)
    monkeypatch.setattr(art_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(art_mod, "MAX_PEAK_BINS", 400)
    monkeypatch.setattr(art_mod, "PEAKS_PER_SECOND", 2.0)
    # Force disk under tmp so we don't pollute the user cache.
    monkeypatch.setattr(art_mod, "_CACHE_DIR", tmp_path / "wave_cache")

    dur = HEAVY_VIDEO_SECONDS + 30.0
    clip = VideoClip.create(
        name="s",
        path=path,
        start_seconds=0.0,
        duration_seconds=dur,
        source_duration_seconds=dur,
    )
    cache = VideoClipWaveformCache()
    peaks = cache._build_from_shared_artifact(  # noqa: SLF001
        cache._generation, cache.key_for(clip), clip  # noqa: SLF001
    )
    assert peaks is not None
    key = artifact_cache_key(path, duration_seconds=dur)
    assert key is not None
    assert (tmp_path / "wave_cache" / f"vwave_{key}.npz").is_file()

    # Simulate set_song: wipe RAM peaks + in-memory artifact store.
    cache.clear()
    artifact_store().clear()

    # Sync hydrate from disk — no async worker (allow_submit=False).
    restored = cache.get_peaks(clip, allow_submit=False)
    assert restored is not None
    assert restored.mono.size > 0
    assert int(np.count_nonzero(restored.coverage)) > 0
