"""Music-lane stand-in waveform from embedded video audio."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cueplayer.domain.models import VideoClip
from cueplayer.media.video_music_standin import (
    _downsample_to_overview,
    build_music_standin_from_video,
)
from cueplayer.media.video_waveform_artifact import (
    ARTIFACT_FORMAT_VERSION,
    PEAKS_PER_SECOND,
    artifact_bin_count,
    artifact_has_false_zero_gaps,
    artifact_store,
    build_artifact_continuous,
    load_artifact_from_disk,
    save_artifact_to_disk,
    artifact_cache_key,
)
from tests.media.test_video_audio_loader import _make_clip_with_tone


def test_build_music_standin_from_short_video(tmp_path: Path) -> None:
    path = tmp_path / "short.mp4"
    _make_clip_with_tone(path, seconds=0.8)
    clip = VideoClip.create(
        name="v",
        path=path,
        start_seconds=0.0,
        duration_seconds=0.8,
        source_duration_seconds=0.8,
    )
    buf = build_music_standin_from_video(clip, timeline_duration=0.8)
    assert buf is not None
    assert buf.duration_seconds == pytest.approx(0.8, abs=0.25)
    assert buf.mono.size > 10
    assert float(np.max(np.abs(buf.mono))) > 0.0


def test_build_music_standin_places_clip_after_timeline_start(tmp_path: Path) -> None:
    path = tmp_path / "offset.mp4"
    _make_clip_with_tone(path, seconds=0.5)
    clip = VideoClip.create(
        name="v",
        path=path,
        start_seconds=1.0,
        duration_seconds=0.5,
        source_duration_seconds=0.5,
    )
    buf = build_music_standin_from_video(clip, timeline_duration=2.0)
    assert buf is not None
    assert buf.duration_seconds == pytest.approx(2.0, abs=0.3)
    # Leading second should be near-silent; clip region has energy.
    sr = buf.sample_rate
    head = buf.mono[: int(0.5 * sr)]
    body = buf.mono[int(1.0 * sr) : int(1.4 * sr)]
    assert float(np.max(np.abs(head))) < 0.05
    assert float(np.max(np.abs(body))) > 0.01


def test_downsample_overview_keeps_signed_peaks() -> None:
    """Abs-only overview used to paint Music lane as bottom-half comb only."""
    sr = 1000
    samples = np.zeros(1000, dtype=np.float32)
    samples[50] = -0.9
    samples[150] = 0.8
    out = _downsample_to_overview(samples, sr, overview_hz=10)
    assert out[0] < 0
    assert out[1] > 0


def test_build_music_standin_honors_cancel_check(tmp_path: Path) -> None:
    path = tmp_path / "short.mp4"
    _make_clip_with_tone(path, seconds=0.5)
    clip = VideoClip.create(
        name="v",
        path=path,
        start_seconds=0.0,
        duration_seconds=0.5,
        source_duration_seconds=0.5,
    )
    assert build_music_standin_from_video(
        clip, timeline_duration=0.5, cancel_check=lambda: True
    ) is None


def test_heavy_standin_uses_continuous_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multi-hour clips must scan continuously — no sparse 12s zero islands."""
    from cueplayer.media import video_music_standin as standin_mod
    from cueplayer.media import video_waveform_artifact as art_mod
    from cueplayer.media.video_audio_loader import VideoAudioBuffer

    path = tmp_path / "long.mp4"
    path.write_bytes(b"fake")
    clip = VideoClip.create(
        name="long",
        path=path,
        start_seconds=0.0,
        duration_seconds=7200.0,
        source_duration_seconds=7200.0,
    )
    calls: list[float] = []

    def _fake_load(
        p: Path,
        *,
        start_seconds: float = 0.0,
        max_duration_seconds: float | None = None,
    ) -> VideoAudioBuffer:
        del p
        calls.append(float(start_seconds))
        sr = 1000
        n = max(1, int(round(float(max_duration_seconds or 1.0) * sr)))
        samples = np.full((n, 2), 0.2, dtype=np.float32)
        return VideoAudioBuffer(
            path=path,
            sample_rate=sr,
            samples=samples,
            origin_seconds=float(start_seconds),
        )

    monkeypatch.setattr(art_mod, "load_video_audio", _fake_load)
    monkeypatch.setattr(standin_mod, "load_video_audio", _fake_load)
    monkeypatch.setattr(art_mod.time, "sleep", lambda _s: None)
    # Keep test fast: shrink chunk + duration via monkeypatch on constants.
    monkeypatch.setattr(art_mod, "CHUNK_SECONDS", 30.0)
    monkeypatch.setattr(art_mod, "MAX_PEAK_BINS", 500)
    monkeypatch.setattr(art_mod, "PEAKS_PER_SECOND", 0.5)

    art_mod.artifact_store().clear()
    buf = build_music_standin_from_video(clip, timeline_duration=7200.0)
    assert buf is not None
    # Contiguous chunks advance by ~CHUNK_SECONDS, not 12s sparse probes.
    assert len(calls) >= 2
    gaps = [calls[i + 1] - calls[i] for i in range(len(calls) - 1)]
    assert all(g < 60.0 for g in gaps[:20])
    # No fabricated pending holes inside covered region.
    finite = np.isfinite(buf.mono)
    if np.any(finite):
        # Contiguous prefix from clip start — no island pattern.
        prefix = int(np.argmax(~finite)) if not np.all(finite) else finite.size
        assert prefix > 10 or np.all(finite)
