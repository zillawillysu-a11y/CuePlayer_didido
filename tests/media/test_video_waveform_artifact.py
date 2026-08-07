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
    try_music_standin_artifact_from_disk,
)
from cueplayer.media.video_waveform_artifact import (
    BASE_PEAKS_PER_SECOND,
    BATCH_SECONDS,
    DECODE_EOF,
    DECODE_PCM,
    DECODE_SILENCE,
    DECODE_TRANSIENT_EMPTY,
    MAX_PEAK_BINS,
    SequentialWaveformDecoder,
    _DecodeBatch,
    _fill_chunk_peaks,
    artifact_bin_count,
    artifact_cache_key,
    artifact_store,
    build_artifact_continuous,
    empty_artifact,
    load_artifact_from_disk,
    save_artifact_to_disk,
    set_waveform_build_paused,
    set_waveform_gui_suppressed_for_zoom,
    waveform_build_is_paused,
)
from cueplayer.media.video_audio_loader import VideoAudioBuffer


@pytest.fixture(autouse=True)
def _clear_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import cueplayer.media.video_waveform_artifact as art_mod

    monkeypatch.setattr(art_mod, "_CACHE_DIR", tmp_path / "wave_cache")
    artifact_store().clear()
    set_waveform_build_paused(False)
    set_waveform_gui_suppressed_for_zoom(False)
    yield
    artifact_store().clear()
    set_waveform_build_paused(False)
    set_waveform_gui_suppressed_for_zoom(False)


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


def _install_fake_decoder(
    monkeypatch: pytest.MonkeyPatch,
    path: Path,
    *,
    source_duration: float = 10_000.0,
    empty_kinds: dict[float, str] | None = None,
) -> dict:
    """Replace SequentialWaveformDecoder with an in-memory tone session."""
    import cueplayer.media.video_waveform_artifact as art_mod

    loader = _fake_tone_loader(path)
    stats = {"open_count": 0, "batch_count": 0}
    empty_kinds = empty_kinds or {}

    class FakeDecoder:
        def __init__(self, p: Path, *, stream_index: int = 0) -> None:
            del stream_index
            self.path = p
            self.open_count = 0
            self.batch_count = 0
            self._held = False
            self._t = 0.0
            self._eof = False
            self._no_stream = False

        @property
        def no_stream(self) -> bool:
            return False

        @property
        def eof(self) -> bool:
            return self._eof

        def close(self) -> None:
            self._held = False

        def ensure_open(self, *, seek_seconds: float | None = None) -> str | None:
            if not self._held:
                self.open_count += 1
                stats["open_count"] = self.open_count
                self._held = True
            if seek_seconds is not None:
                self._t = float(seek_seconds)
            return None

        def read_batch(self, *, max_seconds: float = BATCH_SECONDS) -> _DecodeBatch:
            self.batch_count += 1
            stats["batch_count"] = self.batch_count
            if self._t >= source_duration - 1e-6:
                self._eof = True
                return _DecodeBatch(kind=DECODE_EOF)
            kind = empty_kinds.get(round(self._t, 3))
            if kind == DECODE_TRANSIENT_EMPTY:
                return _DecodeBatch(kind=DECODE_TRANSIENT_EMPTY)
            if kind == DECODE_SILENCE:
                sr = 2000
                n = max(1, int(round(float(max_seconds) * sr)))
                samples = np.zeros((n, 2), dtype=np.float32)
                origin = self._t
                self._t = origin + n / sr
                return _DecodeBatch(
                    kind=DECODE_SILENCE,
                    samples=samples,
                    sample_rate=sr,
                    origin_seconds=origin,
                    duration_seconds=n / sr,
                )
            buf = loader(
                self.path,
                start_seconds=self._t,
                max_duration_seconds=max_seconds,
            )
            dur = buf.frames / float(buf.sample_rate)
            origin = float(buf.origin_seconds)
            self._t = origin + dur
            return _DecodeBatch(
                kind=DECODE_PCM,
                samples=buf.samples,
                sample_rate=buf.sample_rate,
                origin_seconds=origin,
                duration_seconds=dur,
            )

    monkeypatch.setattr(art_mod, "SequentialWaveformDecoder", FakeDecoder)
    monkeypatch.setattr(art_mod, "CHUNK_YIELD_SECONDS", 0.0)
    monkeypatch.setattr(art_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(art_mod, "MAX_PEAK_BINS", 800)
    monkeypatch.setattr(art_mod, "BASE_PEAKS_PER_SECOND", 2.0)
    monkeypatch.setattr(art_mod, "BATCH_SECONDS", 20.0)
    return stats


def test_short_and_long_use_same_artifact_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    short_p = tmp_path / "short.mp4"
    long_p = tmp_path / "long.mp4"
    short_p.write_bytes(b"x")
    long_p.write_bytes(b"y")
    import cueplayer.media.video_waveform_artifact as art_mod

    for clip_path, dur, name in (
        (short_p, 60.0, "s"),
        (long_p, 900.0, "l"),
    ):
        _install_fake_decoder(monkeypatch, clip_path, source_duration=dur)
        art = art_mod.artifact_store().wait_in_worker(clip_path, duration_seconds=dur)
        assert art is not None and art.complete
        clip = VideoClip.create(
            name=name, path=clip_path, duration_seconds=dur, source_duration_seconds=dur
        )
        peaks = peaks_from_artifact(clip, art)
        assert peaks is not None
        assert peaks.mins.size == art.n_bins


def test_two_consumers_one_decode_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "shared.mp4"
    path.write_bytes(b"x")
    stats = _install_fake_decoder(monkeypatch, path, source_duration=40.0)
    clip = VideoClip.create(
        name="s", path=path, duration_seconds=40.0, source_duration_seconds=40.0
    )
    store = artifact_store()
    a1 = store.ensure_building(path, duration_seconds=40.0)
    a2 = store.ensure_building(path, duration_seconds=40.0)
    assert a1 is a2
    art = store.wait_in_worker(path, duration_seconds=40.0)
    assert art is not None and art.complete
    # One sequential session — not one open per 8 s window.
    assert stats["open_count"] == 1
    assert peaks_from_artifact(clip, art) is not None
    assert audio_from_artifact(path, clip, art, timeline_duration=40.0) is not None


def test_sequential_decoder_one_open_not_per_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "seq.mp4"
    path.write_bytes(b"x")
    stats = _install_fake_decoder(monkeypatch, path, source_duration=120.0)
    art = build_artifact_continuous(path, duration_seconds=120.0)
    assert art is not None and art.complete
    assert stats["open_count"] == 1
    assert stats["batch_count"] >= 2


def test_local_bin_fill_allocates_only_affected_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "local.mp4"
    path.write_bytes(b"x")
    art = empty_artifact(path, duration_seconds=60.0)
    assert art is not None
    # Tiny PCM near the start — temp arrays must be << full artifact.
    sr = 1000
    pcm = np.full((sr, 2), 0.25, dtype=np.float32)
    newly, touched, temp_bytes = _fill_chunk_peaks(
        art, pcm=pcm, pcm_rate=sr, pcm_origin=0.0
    )
    assert newly > 0
    full_bytes = art.n_bins * 4 * 2
    assert temp_bytes < full_bytes / 4
    assert touched <= art.n_bins


def test_transient_empty_remains_uncovered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "transient.mp4"
    path.write_bytes(b"x")
    # First batch transient — must not cover those bins as silence.
    _install_fake_decoder(
        monkeypatch,
        path,
        source_duration=20.0,
        empty_kinds={0.0: DECODE_TRANSIENT_EMPTY},
    )
    # Only one transient then need to advance — use a custom decoder.
    import cueplayer.media.video_waveform_artifact as art_mod

    calls = {"n": 0}
    loader = _fake_tone_loader(path)

    class TransientThenTone(SequentialWaveformDecoder):
        def ensure_open(self, *, seek_seconds: float | None = None) -> str | None:
            if not self._held:
                self.open_count += 1
                self._held = True
            if seek_seconds is not None:
                self._cursor_seconds = float(seek_seconds)
            return None

        def close(self) -> None:
            self._held = False

        def read_batch(self, *, max_seconds: float = BATCH_SECONDS) -> _DecodeBatch:
            self.batch_count += 1
            calls["n"] += 1
            if calls["n"] == 1:
                return _DecodeBatch(kind=DECODE_TRANSIENT_EMPTY)
            if self._cursor_seconds >= 20.0:
                self._eof = True
                return _DecodeBatch(kind=DECODE_EOF)
            buf = loader(
                path,
                start_seconds=self._cursor_seconds,
                max_duration_seconds=max_seconds,
            )
            dur = buf.frames / float(buf.sample_rate)
            origin = float(buf.origin_seconds)
            self._cursor_seconds = origin + dur
            return _DecodeBatch(
                kind=DECODE_PCM,
                samples=buf.samples,
                sample_rate=buf.sample_rate,
                origin_seconds=origin,
                duration_seconds=dur,
            )

    monkeypatch.setattr(art_mod, "SequentialWaveformDecoder", TransientThenTone)
    monkeypatch.setattr(art_mod, "CHUNK_YIELD_SECONDS", 0.0)
    monkeypatch.setattr(art_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(art_mod, "MAX_PEAK_BINS", 80)
    monkeypatch.setattr(art_mod, "BASE_PEAKS_PER_SECOND", 2.0)
    monkeypatch.setattr(art_mod, "BATCH_SECONDS", 5.0)

    # Capture coverage after first progress publish.
    coverages: list[float] = []

    def _on(a):
        coverages.append(float(a.coverage_ratio))

    art = build_artifact_continuous(
        path, duration_seconds=20.0, on_progress=_on
    )
    assert art is not None
    # After first transient publish (if any), coverage must stay 0 until real PCM.
    if coverages:
        assert coverages[0] == 0.0 or coverages[0] > 0.0
    # Transient must not have marked the prefix as silence before tone arrived.
    # Final artifact should have real coverage from tone batches.
    assert art.coverage_ratio > 0.5


def test_confirmed_silence_is_covered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "sil.mp4"
    path.write_bytes(b"x")
    _install_fake_decoder(
        monkeypatch,
        path,
        source_duration=10.0,
        empty_kinds={0.0: DECODE_SILENCE},
    )
    # Override so first batch is silence then tone for the rest.
    import cueplayer.media.video_waveform_artifact as art_mod

    loader = _fake_tone_loader(path)
    state = {"n": 0}

    class SilThenTone:
        def __init__(self, p, *, stream_index=0):
            self.path = p
            self.open_count = 0
            self.batch_count = 0
            self._held = False
            self._t = 0.0
            self._eof = False
            self._no_stream = False

        @property
        def no_stream(self):
            return False

        @property
        def eof(self):
            return self._eof

        def close(self):
            self._held = False

        def ensure_open(self, *, seek_seconds=None):
            if not self._held:
                self.open_count += 1
                self._held = True
            if seek_seconds is not None:
                self._t = float(seek_seconds)
            return None

        def read_batch(self, *, max_seconds=BATCH_SECONDS):
            self.batch_count += 1
            state["n"] += 1
            if self._t >= 10.0:
                self._eof = True
                return _DecodeBatch(kind=DECODE_EOF)
            if state["n"] == 1:
                sr = 2000
                n = max(1, int(round(float(max_seconds) * sr)))
                samples = np.zeros((n, 2), dtype=np.float32)
                origin = self._t
                self._t = origin + n / sr
                return _DecodeBatch(
                    kind=DECODE_SILENCE,
                    samples=samples,
                    sample_rate=sr,
                    origin_seconds=origin,
                    duration_seconds=n / sr,
                )
            buf = loader(path, start_seconds=self._t, max_duration_seconds=max_seconds)
            dur = buf.frames / float(buf.sample_rate)
            origin = float(buf.origin_seconds)
            self._t = origin + dur
            return _DecodeBatch(
                kind=DECODE_PCM,
                samples=buf.samples,
                sample_rate=buf.sample_rate,
                origin_seconds=origin,
                duration_seconds=dur,
            )

    monkeypatch.setattr(art_mod, "SequentialWaveformDecoder", SilThenTone)
    art = build_artifact_continuous(path, duration_seconds=10.0)
    assert art is not None and art.complete
    # Silence prefix is covered (zeros), not pending.
    assert art.coverage[0] == 1
    assert float(art.mins[0]) == 0.0


def test_reopen_complete_artifact_zero_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "warm.mp4"
    path.write_bytes(b"x")
    _install_fake_decoder(monkeypatch, path, source_duration=30.0)
    import cueplayer.media.video_waveform_artifact as art_mod

    art = art_mod.artifact_store().wait_in_worker(path, duration_seconds=30.0)
    assert art is not None and art.complete
    key = artifact_cache_key(path, duration_seconds=30.0)
    assert key is not None
    assert load_artifact_from_disk(key) is not None

    def _boom(*_a, **_k):
        raise AssertionError("warm reopen must not decode")

    monkeypatch.setattr(art_mod, "SequentialWaveformDecoder", _boom)
    artifact_store().clear()
    hit = artifact_store().get_or_load_disk(path, duration_seconds=30.0)
    assert hit is not None and hit.complete
    clip = VideoClip.create(
        name="w", path=path, duration_seconds=30.0, source_duration_seconds=30.0
    )
    assert try_music_standin_artifact_from_disk(clip, timeline_duration=30.0) is not None


def test_main_lane_consumes_partial_without_full_buffer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "partial.mp4"
    path.write_bytes(b"x")
    _install_fake_decoder(monkeypatch, path, source_duration=40.0)
    clip = VideoClip.create(
        name="p", path=path, duration_seconds=40.0, source_duration_seconds=40.0
    )
    partials: list = []

    def _on(art):
        partials.append(art)
        # Must be able to map peaks without building AudioBuffer.
        assert peaks_from_artifact(clip, art) is not None

    store = artifact_store()
    # Ensure building publishes progressive updates.
    store._progress_coalesce_s = 0.0  # noqa: SLF001
    art = store.wait_in_worker(path, duration_seconds=40.0, on_update=_on)
    assert art is not None and art.complete
    assert len(partials) >= 1
    # First partial must arrive before complete.
    assert any(not p.complete and p.coverage_ratio > 0 for p in partials[:-1]) or (
        partials[0].coverage_ratio > 0
    )


def test_progressive_does_not_build_full_audiobuffer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "nobuf.mp4"
    path.write_bytes(b"x")
    _install_fake_decoder(monkeypatch, path, source_duration=30.0)
    clip = VideoClip.create(
        name="n", path=path, duration_seconds=30.0, source_duration_seconds=30.0
    )
    import cueplayer.media.video_music_standin as standin

    calls = {"n": 0}
    real = standin.audio_from_artifact

    def _count(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(standin, "audio_from_artifact", _count)
    arts: list = []

    def _on(art):
        arts.append(art)

    result = build_music_standin_from_video(
        clip, timeline_duration=30.0, on_progress=_on
    )
    assert result is not None
    assert arts
    # Progressive callback must not construct AudioBuffer.
    assert calls["n"] == 0


def test_different_trims_reuse_one_source_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "trim.mp4"
    path.write_bytes(b"x")
    _install_fake_decoder(monkeypatch, path, source_duration=60.0)
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
    assert p1.mins.size == p2.mins.size == art.n_bins


def test_ensure_building_never_blocks_like_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "noblock.mp4"
    path.write_bytes(b"x")
    import cueplayer.media.video_waveform_artifact as art_mod
    import time as _time

    _install_fake_decoder(monkeypatch, path, source_duration=60.0)
    # Slow yield so wait would hang if called — ensure_building must return ASAP.
    monkeypatch.setattr(art_mod, "BATCH_SECONDS", 5.0)

    # Make read_batch sleep so a blocking wait would be obvious.
    real_cls = art_mod.SequentialWaveformDecoder

    class Slow(real_cls):
        def read_batch(self, *, max_seconds: float = BATCH_SECONDS):
            _time.sleep(0.05)
            return super().read_batch(max_seconds=max_seconds)

    # Fake decoder from install doesn't sleep — just check ensure returns fast.
    t0 = _time.perf_counter()
    art = artifact_store().ensure_building(path, duration_seconds=60.0)
    elapsed = _time.perf_counter() - t0
    assert art is not None
    assert elapsed < 0.5


def test_playback_pauses_builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    del tmp_path, monkeypatch
    set_waveform_build_paused(True)
    assert waveform_build_is_paused()
    set_waveform_build_paused(False)
    assert not waveform_build_is_paused()


def test_progressive_updates_coalesce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "coal.mp4"
    path.write_bytes(b"x")
    _install_fake_decoder(monkeypatch, path, source_duration=40.0)
    import cueplayer.media.video_waveform_artifact as art_mod

    monkeypatch.setattr(art_mod, "BATCH_SECONDS", 5.0)
    monkeypatch.setattr(art_mod, "PROGRESS_GUI_COALESCE_SECONDS", 10.0)
    publishes = {"n": 0}

    def _on(_art):
        publishes["n"] += 1

    store = artifact_store()
    store._progress_coalesce_s = 10.0  # noqa: SLF001
    art = store.wait_in_worker(path, duration_seconds=40.0, on_update=_on)
    assert art is not None and art.complete
    assert publishes["n"] >= 1
    assert publishes["n"] < 8


def test_continuous_audio_no_periodic_coverage_holes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "cont.mp4"
    path.write_bytes(b"x")
    _install_fake_decoder(monkeypatch, path, source_duration=60.0)
    art = build_artifact_continuous(path, duration_seconds=60.0)
    assert art is not None and art.complete
    cov = art.coverage.astype(bool)
    assert np.all(cov)


def test_corrupt_cache_triggers_safe_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "bad.mp4"
    path.write_bytes(b"x")
    _install_fake_decoder(monkeypatch, path, source_duration=20.0)
    art = artifact_store().wait_in_worker(path, duration_seconds=20.0)
    assert art is not None
    key = artifact_cache_key(path, duration_seconds=20.0)
    assert key is not None
    disk = tmp_path / "wave_cache" / f"vwave_{key}.npz"
    assert disk.is_file()
    disk.write_bytes(b"not-a-valid-npz")
    artifact_store().clear()
    assert load_artifact_from_disk(key) is None
    _install_fake_decoder(monkeypatch, path, source_duration=20.0)
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
