"""Unified VideoWaveformArtifact — one decode, durable cache, all consumers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cueplayer.domain.models import VideoClip
from cueplayer.media.video_clip_waveform import (
    VideoClipWaveformCache,
    peaks_from_artifact,
)
from cueplayer.media.video_music_standin import (
    audio_from_artifact,
    build_music_standin_from_video,
    try_music_standin_from_disk,
)
from cueplayer.media.video_waveform_artifact import (
    BASE_PEAKS_PER_SECOND,
    MAX_PEAK_BINS,
    artifact_bin_count,
    artifact_cache_key,
    artifact_store,
    build_artifact_continuous,
    load_artifact_from_disk,
    save_artifact_to_disk,
    set_waveform_build_paused,
    waveform_build_is_paused,
)
from cueplayer.media.video_audio_loader import VideoAudioBuffer


@pytest.fixture(autouse=True)
def _clear_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import cueplayer.media.video_waveform_artifact as art_mod

    monkeypatch.setattr(art_mod, "_CACHE_DIR", tmp_path / "wave_cache")
    artifact_store().clear()
    set_waveform_build_paused(False)
    yield
    artifact_store().clear()
    set_waveform_build_paused(False)


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


def _patch_fast_build(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    import cueplayer.media.video_waveform_artifact as art_mod

    monkeypatch.setattr(art_mod, "load_video_audio", _fake_tone_loader(path))
    monkeypatch.setattr(art_mod, "CHUNK_SECONDS", 20.0)
    monkeypatch.setattr(art_mod, "CHUNK_YIELD_SECONDS", 0.0)
    monkeypatch.setattr(art_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(art_mod, "MAX_PEAK_BINS", 800)
    monkeypatch.setattr(art_mod, "BASE_PEAKS_PER_SECOND", 2.0)


def test_short_and_long_use_same_artifact_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    short_p = tmp_path / "short.mp4"
    long_p = tmp_path / "long.mp4"
    short_p.write_bytes(b"x")
    long_p.write_bytes(b"y")
    _patch_fast_build(monkeypatch, short_p)
    import cueplayer.media.video_waveform_artifact as art_mod

    monkeypatch.setattr(art_mod, "load_video_audio", _fake_tone_loader(short_p))

    short = VideoClip.create(
        name="s", path=short_p, duration_seconds=60.0, source_duration_seconds=60.0
    )
    long = VideoClip.create(
        name="l",
        path=long_p,
        duration_seconds=900.0,
        source_duration_seconds=900.0,
    )
    cache = VideoClipWaveformCache()
    # Both go through shared ensure_building — no heavy skip.
    for clip, path, dur in (
        (short, short_p, 60.0),
        (long, long_p, 900.0),
    ):
        monkeypatch.setattr(art_mod, "load_video_audio", _fake_tone_loader(path))
        art = art_mod.artifact_store().wait_in_worker(path, duration_seconds=dur)
        assert art is not None and art.complete
        peaks = peaks_from_artifact(clip, art)
        assert peaks is not None
        assert peaks.mins.size == art.n_bins


def test_two_consumers_one_decode_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "shared.mp4"
    path.write_bytes(b"x")
    _patch_fast_build(monkeypatch, path)
    import cueplayer.media.video_waveform_artifact as art_mod

    decode_calls = {"n": 0}
    base = _fake_tone_loader(path)

    def _count(*a, **k):
        decode_calls["n"] += 1
        return base(*a, **k)

    monkeypatch.setattr(art_mod, "load_video_audio", _count)
    clip = VideoClip.create(
        name="s", path=path, duration_seconds=40.0, source_duration_seconds=40.0
    )
    store = artifact_store()
    # Two ensure_building calls must dedupe to one job.
    a1 = store.ensure_building(path, duration_seconds=40.0)
    a2 = store.ensure_building(path, duration_seconds=40.0)
    assert a1 is a2
    art = store.wait_in_worker(path, duration_seconds=40.0)
    assert art is not None and art.complete
    # Contiguous 20s chunks over 40s → about 2 decode windows (not doubled).
    assert decode_calls["n"] <= 4
    # Music + Video lane both map the same art.
    assert peaks_from_artifact(clip, art) is not None
    assert audio_from_artifact(path, clip, art, timeline_duration=40.0) is not None


def test_reopen_complete_artifact_zero_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "warm.mp4"
    path.write_bytes(b"x")
    _patch_fast_build(monkeypatch, path)
    import cueplayer.media.video_waveform_artifact as art_mod

    art = art_mod.artifact_store().wait_in_worker(path, duration_seconds=30.0)
    assert art is not None and art.complete
    key = artifact_cache_key(path, duration_seconds=30.0)
    assert key is not None
    assert load_artifact_from_disk(key) is not None

    decode_calls = {"n": 0}

    def _boom(*_a, **_k):
        decode_calls["n"] += 1
        raise AssertionError("warm reopen must not decode")

    monkeypatch.setattr(art_mod, "load_video_audio", _boom)
    artifact_store().clear()
    hit = artifact_store().get_or_load_disk(path, duration_seconds=30.0)
    assert hit is not None and hit.complete
    assert decode_calls["n"] == 0
    clip = VideoClip.create(
        name="w", path=path, duration_seconds=30.0, source_duration_seconds=30.0
    )
    assert try_music_standin_from_disk(clip, timeline_duration=30.0) is not None


def test_different_trims_reuse_one_source_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trim.mp4"
    path.write_bytes(b"x")
    _patch_fast_build(monkeypatch, path)
    art = artifact_store().wait_in_worker(path, duration_seconds=60.0)
    assert art is not None
    c1 = VideoClip.create(
        name="a",
        path=path,
        start_seconds=0.0,
        duration_seconds=10.0,
        source_in_seconds=5.0,
        source_duration_seconds=60.0,
    )
    c1.source_out_seconds = 15.0
    c2 = VideoClip.create(
        name="b",
        path=path,
        start_seconds=0.0,
        duration_seconds=20.0,
        source_in_seconds=20.0,
        source_duration_seconds=60.0,
    )
    c2.source_out_seconds = 40.0
    p1 = peaks_from_artifact(c1, art)
    p2 = peaks_from_artifact(c2, art)
    assert p1 is not None and p2 is not None
    # Same source envelope length.
    assert p1.mins.size == p2.mins.size == art.n_bins


def test_ensure_building_never_blocks_like_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "noblock.mp4"
    path.write_bytes(b"x")
    import cueplayer.media.video_waveform_artifact as art_mod

    monkeypatch.setattr(art_mod, "load_video_audio", _fake_tone_loader(path))
    monkeypatch.setattr(art_mod, "CHUNK_SECONDS", 5.0)
    # Slow yield so wait would hang if called — ensure_building must return ASAP.
    monkeypatch.setattr(art_mod, "CHUNK_YIELD_SECONDS", 2.0)
    monkeypatch.setattr(art_mod, "MAX_PEAK_BINS", 100)
    monkeypatch.setattr(art_mod, "BASE_PEAKS_PER_SECOND", 1.0)

    import time as _time

    t0 = _time.perf_counter()
    art = artifact_store().ensure_building(path, duration_seconds=60.0)
    elapsed = _time.perf_counter() - t0
    assert art is not None
    assert elapsed < 0.5  # must not wait for full build


def test_playback_pauses_builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "pause.mp4"
    path.write_bytes(b"x")
    set_waveform_build_paused(True)
    assert waveform_build_is_paused()
    set_waveform_build_paused(False)
    assert not waveform_build_is_paused()


def test_progressive_updates_coalesce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "coal.mp4"
    path.write_bytes(b"x")
    _patch_fast_build(monkeypatch, path)
    import cueplayer.media.video_waveform_artifact as art_mod

    monkeypatch.setattr(art_mod, "CHUNK_SECONDS", 5.0)
    monkeypatch.setattr(art_mod, "PROGRESS_GUI_COALESCE_SECONDS", 10.0)
    publishes = {"n": 0}

    def _on(_art):
        publishes["n"] += 1

    store = artifact_store()
    store._progress_coalesce_s = 10.0  # noqa: SLF001
    art = store.wait_in_worker(path, duration_seconds=40.0, on_update=_on)
    assert art is not None and art.complete
    # First partial + final (and maybe one more) — not one per chunk.
    assert publishes["n"] >= 1
    assert publishes["n"] < 8


def test_continuous_audio_no_periodic_coverage_holes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "cont.mp4"
    path.write_bytes(b"x")
    _patch_fast_build(monkeypatch, path)
    art = build_artifact_continuous(path, duration_seconds=60.0)
    assert art is not None and art.complete
    # Contiguous coverage — no island holes inside prefix.
    cov = art.coverage.astype(bool)
    assert np.all(cov)


def test_corrupt_cache_triggers_safe_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "bad.mp4"
    path.write_bytes(b"x")
    _patch_fast_build(monkeypatch, path)
    art = artifact_store().wait_in_worker(path, duration_seconds=20.0)
    assert art is not None
    key = artifact_cache_key(path, duration_seconds=20.0)
    assert key is not None
    disk = tmp_path / "wave_cache" / f"vwave_{key}.npz"
    assert disk.is_file()
    disk.write_bytes(b"not-a-valid-npz")
    artifact_store().clear()
    assert load_artifact_from_disk(key) is None
    rebuilt = artifact_store().wait_in_worker(path, duration_seconds=20.0)
    assert rebuilt is not None and rebuilt.complete


def test_memory_bound() -> None:
    dur = 15 * 60.0
    n = artifact_bin_count(dur)
    assert n <= MAX_PEAK_BINS
    artifact_bytes = n * (4 + 4 + 1)
    full_rate = dur * 48000 * 4
    assert artifact_bytes < full_rate / 50.0
    assert n == int(np.ceil(dur * BASE_PEAKS_PER_SECOND)) or n == MAX_PEAK_BINS
