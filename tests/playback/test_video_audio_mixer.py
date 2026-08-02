"""VideoAudioMixer: pure frame-math tests (no real file decode — the cache is
injected directly so these stay fast and independent of media/test_video_audio_loader.py).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest

from cueplayer.domain.models import Song, VideoClip
from cueplayer.media.video_audio_loader import VideoAudioBuffer
from cueplayer.playback.video_audio_mixer import VideoAudioMixer, _CachedPcm

SR = 48000


def _inject(mixer: VideoAudioMixer, clip: VideoClip, samples: np.ndarray) -> None:
    """Bypass real decoding: pretend `clip` was already decoded + resampled.

    Buffer index 0 == clip.source_in (windowed decode contract).
    """
    origin = float(clip.source_in_seconds)
    dur = samples.shape[0] / float(mixer._playback_rate)
    key = (
        str(clip.path),
        mixer._playback_rate,
        round(origin, 2),
        round(dur, 2),
    )
    mixer._cache[clip.id] = [
        _CachedPcm(samples=samples, origin_seconds=origin, key=key)
    ]


def _constant(seconds: float, value: float) -> np.ndarray:
    n = int(round(seconds * SR))
    return np.full((n, 2), value, dtype=np.float32)


def test_chunk_at_silent_with_no_song() -> None:
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    out = mixer.chunk_at(0, 100)
    assert out.shape == (100, 2)
    assert np.all(out == 0.0)


def test_chunk_at_silent_outside_any_clip() -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="c", path=Path("c.mp4"), start_seconds=5.0, duration_seconds=2.0)
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)
    _inject(mixer, clip, _constant(2.0, 0.5))

    out = mixer.chunk_at(0, 100)  # well before clip.start_seconds
    assert np.all(out == 0.0)


def test_chunk_at_returns_clip_audio_scaled_by_volume() -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="c", path=Path("c.mp4"), start_seconds=0.0, duration_seconds=2.0, volume=0.5)
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)
    _inject(mixer, clip, _constant(2.0, 0.8))

    out = mixer.chunk_at(0, 1000)
    assert np.allclose(out, 0.4, atol=1e-5)  # 0.8 * 0.5


def test_chunk_at_respects_source_in_offset() -> None:
    """Windowed buffer: samples[0] is source_in; timeline offset 0 maps to index 0."""
    song = Song.create("Song")
    clip = VideoClip.create(
        name="c", path=Path("c.mp4"), start_seconds=1.0, source_in_seconds=3.0, duration_seconds=2.0
    )
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)

    # Window covering source 3.0s..5.0s — value encodes absolute source frame.
    source_in_frame = int(3.0 * SR)
    ramp = (np.arange(2 * SR, dtype=np.float32) + source_in_frame) * 1e-6
    samples = np.stack([ramp, ramp], axis=1)
    _inject(mixer, clip, samples)

    start_frame = int(1.0 * SR)  # song-timeline frame at clip.start_seconds
    out = mixer.chunk_at(start_frame, 5)
    expected_src0 = source_in_frame * 1e-6
    assert out[0, 0] == pytest.approx(expected_src0, abs=1e-6)
    assert out[4, 0] == pytest.approx(expected_src0 + 4e-6, abs=1e-6)


def test_chunk_at_muted_returns_silence() -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="c", path=Path("c.mp4"), start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)
    mixer.set_muted(True)
    _inject(mixer, clip, _constant(2.0, 0.9))

    out = mixer.chunk_at(0, 100)
    assert np.all(out == 0.0)


def test_chunk_at_skips_hidden_clips() -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="c", path=Path("c.mp4"), start_seconds=0.0, duration_seconds=2.0)
    clip.hidden = True
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)
    _inject(mixer, clip, _constant(2.0, 0.9))

    out = mixer.chunk_at(0, 100)
    assert np.all(out == 0.0)


def test_chunk_at_crossfades_overlap_instead_of_hard_cut() -> None:
    """Overlapping clips accumulate with linear crossfade weights."""
    song = Song.create("Song")
    early = VideoClip.create(name="early", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=5.0)
    late = VideoClip.create(name="late", path=Path("b.mp4"), start_seconds=2.0, duration_seconds=5.0)
    song.add_video_clip(early)
    song.add_video_clip(late)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)
    _inject(mixer, early, _constant(5.0, 0.2))
    _inject(mixer, late, _constant(5.0, 0.8))

    start_frame = int(round(3.5 * SR))
    out = mixer.chunk_at(start_frame, 1)[0, 0]
    assert out == pytest.approx(0.5, abs=1e-4)  # 0.2*0.5 + 0.8*0.5 at overlap midpoint


def test_chunk_at_loops_source_audio_when_timeline_stretched() -> None:
    song = Song.create("Song")
    clip = VideoClip.create(
        name="c",
        path=Path("c.mp4"),
        start_seconds=0.0,
        source_in_seconds=0.0,
        duration_seconds=4.0,
    )
    clip.source_out_seconds = 2.0
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)
    ramp = np.arange(2 * SR, dtype=np.float32) * 1e-6
    samples = np.stack([ramp, ramp], axis=1)
    _inject(mixer, clip, samples)

    at_wrap = int(2.0 * SR)
    out = mixer.chunk_at(at_wrap, 3)[0, 0]
    assert out == pytest.approx(0.0, abs=1e-6)
    out_later = mixer.chunk_at(at_wrap + 1, 1)[0, 0]
    assert out_later == pytest.approx(1e-6, abs=1e-7)


def test_chunk_at_missing_cache_entry_is_silent_not_a_crash() -> None:
    """Preload not finished yet (or decode failed) -> silence, never a realtime decode."""
    song = Song.create("Song")
    clip = VideoClip.create(name="c", path=Path("c.mp4"), start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)

    out = mixer.chunk_at(0, 100)
    assert np.all(out == 0.0)


def test_preload_prunes_cache_for_removed_clips() -> None:
    clip = VideoClip.create(name="c", path=Path("c.mp4"))
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    _inject(mixer, clip, _constant(1.0, 0.5))
    assert clip.id in mixer._cache

    mixer.preload([])  # clip removed from the song
    assert clip.id not in mixer._cache


def test_set_playback_rate_change_clears_cache() -> None:
    clip = VideoClip.create(name="c", path=Path("c.mp4"))
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    _inject(mixer, clip, _constant(1.0, 0.5))

    mixer.set_playback_rate(44100)
    assert mixer._cache == {}


def test_rapid_window_requests_coalesce_to_latest_need(monkeypatch: pytest.MonkeyPatch) -> None:
    """While a decode job is running, later seeks only stash the latest need —
    they must not queue N full-window decodes under av_path_lock."""
    song = Song.create("Song")
    clip = VideoClip.create(
        name="c",
        path=Path("c.mp4"),
        start_seconds=0.0,
        duration_seconds=600.0,
        source_duration_seconds=600.0,
    )
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)

    started = threading.Event()
    release = threading.Event()
    decode_calls: list[float] = []

    def _fake_get(path, *, start_seconds=0.0, max_duration_seconds=None):  # noqa: ANN001
        del path, max_duration_seconds
        decode_calls.append(float(start_seconds))
        started.set()
        assert release.wait(timeout=2.0)
        n = int(0.5 * SR)
        samples = np.zeros((n, 2), dtype=np.float32)
        return VideoAudioBuffer(
            path=Path("c.mp4"),
            sample_rate=SR,
            samples=samples,
            origin_seconds=float(start_seconds),
        )

    monkeypatch.setattr(
        "cueplayer.playback.video_audio_mixer.get_video_audio", _fake_get
    )

    mixer._request_window(clip, 10.0)
    assert started.wait(timeout=2.0)
    # Thrash seeks while first job holds the worker.
    mixer._request_window(clip, 100.0)
    mixer._request_window(clip, 200.0)
    mixer._request_window(clip, 300.0)
    assert mixer._pending_need[clip.id] == pytest.approx(300.0)
    assert len(decode_calls) == 1

    release.set()
    # Allow follow-up job for the latest pending need.
    deadline = time.monotonic() + 2.0
    while len(decode_calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(decode_calls) == 2
    # Follow-up window starts near the latest need (lookback capped at 8s).
    from cueplayer.media.video_limits import HEAVY_VIDEO_AUDIO_DECODE_SECONDS

    lookback = min(8.0, max(2.0, HEAVY_VIDEO_AUDIO_DECODE_SECONDS * 0.12))
    assert decode_calls[1] == pytest.approx(300.0 - lookback, abs=0.05)


def test_chunk_at_prefetches_before_window_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    """Near the end of a cached window, schedule the next decode early."""
    song = Song.create("Song")
    clip = VideoClip.create(
        name="c",
        path=Path("c.mp4"),
        start_seconds=0.0,
        duration_seconds=600.0,
        source_duration_seconds=600.0,
    )
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)

    # 40s window starting at 0 — playhead near end should prefetch.
    _inject(mixer, clip, _constant(40.0, 0.4))
    requested: list[float] = []

    def _capture(c: VideoClip, source_time: float) -> None:
        requested.append(float(source_time))

    monkeypatch.setattr(mixer, "_request_window", _capture)

    at = int(15.0 * SR)
    out = mixer.chunk_at(at, 256)
    assert float(np.max(np.abs(out))) > 0.0
    assert requested, "expected prefetch near end of window"
    assert requested[0] > 15.0


def test_double_buffer_keeps_previous_window_while_sliding() -> None:
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    clip = VideoClip.create(name="c", path=Path("c.mp4"), duration_seconds=120.0)
    first = _CachedPcm(
        samples=_constant(30.0, 0.5),
        origin_seconds=0.0,
        key=("c.mp4", SR, 0.0, 30.0),
    )
    second = _CachedPcm(
        samples=_constant(30.0, 0.5),
        origin_seconds=20.0,
        key=("c.mp4", SR, 20.0, 30.0),
    )
    mixer._install_window(clip.id, first)
    mixer._install_window(clip.id, second)
    assert len(mixer._cache[clip.id]) == 2
    # Still covered by the older window while the new one starts later.
    assert mixer._find_covering(clip.id, 5.0) is first
    assert mixer._find_covering(clip.id, 25.0) is second


def test_chunk_at_composites_across_window_seam() -> None:
    """Playhead can cross from window A into B without a silent gap."""
    song = Song.create("Song")
    clip = VideoClip.create(
        name="c",
        path=Path("c.mp4"),
        start_seconds=0.0,
        duration_seconds=120.0,
        source_duration_seconds=120.0,
    )
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)
    mixer._install_window(
        clip.id,
        _CachedPcm(
            samples=_constant(30.0, 0.5),
            origin_seconds=0.0,
            key=("c.mp4", SR, 0.0, 30.0),
        ),
    )
    mixer._install_window(
        clip.id,
        _CachedPcm(
            samples=_constant(30.0, 0.7),
            origin_seconds=20.0,
            key=("c.mp4", SR, 20.0, 30.0),
        ),
    )
    # Straddle the first window's end (t=30); second window covers 20..50.
    at = int(29.5 * SR)
    out = mixer.chunk_at(at, int(1.0 * SR))
    assert float(np.min(np.abs(out))) > 0.0
    # Past the first window, prefer the newer buffer's amplitude.
    assert out[-1, 0] == pytest.approx(0.7, abs=1e-4)
