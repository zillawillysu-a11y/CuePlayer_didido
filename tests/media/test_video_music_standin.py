"""Music-lane stand-in from shared VideoWaveformArtifact."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cueplayer.domain.models import VideoClip
from cueplayer.media.video_music_standin import build_music_standin_from_video
from cueplayer.media.video_waveform_artifact import artifact_store
from tests.media.test_video_audio_loader import _make_clip_with_tone


@pytest.fixture(autouse=True)
def _clear_store() -> None:
    artifact_store().clear()
    yield
    artifact_store().clear()


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
    finite = buf.mono[np.isfinite(buf.mono)]
    assert finite.size > 0
    assert float(np.max(np.abs(finite))) > 0.0


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
    sr = buf.sample_rate
    head = buf.mono[: int(0.5 * sr)]
    body = buf.mono[int(1.0 * sr) : int(1.4 * sr)]
    # Leading region pending/empty; clip region has energy.
    head_finite = head[np.isfinite(head)]
    body_finite = body[np.isfinite(body)]
    assert head_finite.size == 0 or float(np.max(np.abs(head_finite))) < 0.05
    assert body_finite.size > 0
    assert float(np.max(np.abs(body_finite))) > 0.01


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
    assert (
        build_music_standin_from_video(
            clip, timeline_duration=0.5, cancel_check=lambda: True
        )
        is None
    )


def test_long_standin_uses_continuous_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Long clips use continuous chunked artifact — not sparse 12s probes."""
    import cueplayer.media.video_waveform_artifact as art_mod
    from cueplayer.media.video_audio_loader import VideoAudioBuffer

    path = tmp_path / "long.mp4"
    path.write_bytes(b"fake")
    clip = VideoClip.create(
        name="long",
        path=path,
        start_seconds=0.0,
        duration_seconds=120.0,
        source_duration_seconds=120.0,
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
    monkeypatch.setattr(art_mod, "CHUNK_SECONDS", 10.0)
    monkeypatch.setattr(art_mod, "CHUNK_YIELD_SECONDS", 0.0)
    monkeypatch.setattr(art_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(art_mod, "MAX_PEAK_BINS", 500)
    monkeypatch.setattr(art_mod, "BASE_PEAKS_PER_SECOND", 2.0)

    art_mod.artifact_store().clear()
    buf = build_music_standin_from_video(clip, timeline_duration=120.0)
    assert buf is not None
    assert len(calls) >= 2
    gaps = [calls[i + 1] - calls[i] for i in range(len(calls) - 1)]
    assert all(g < 20.0 for g in gaps[:20])
