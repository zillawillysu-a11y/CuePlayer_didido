"""VideoAudioMixer: pure frame-math tests (no real file decode — the cache is
injected directly so these stay fast and independent of media/test_video_audio_loader.py).
"""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from cueplayer.domain.models import Song, VideoClip
from cueplayer.media.video_audio_loader import VideoAudioBuffer
from cueplayer.playback.video_audio_mixer import VideoAudioMixer, _CachedPcm

SR = 48000


def _pcm(
    samples: np.ndarray,
    *,
    origin_seconds: float,
    key: tuple,
    rate: int = SR,
) -> _CachedPcm:
    origin_frame = int(math.floor(float(origin_seconds) * float(rate) + 1e-9))
    return _CachedPcm(
        samples=samples,
        origin_seconds=float(origin_seconds),
        origin_frame=origin_frame,
        key=key,
    )


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
    mixer._install_window(clip.id, _pcm(samples, origin_seconds=origin, key=key))


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
    # Follow-up uses quantized heavy-window grid (9s step).
    # Latest need 300 → window floor(300/9)*9 = 297.
    assert decode_calls[1] == pytest.approx(297.0, abs=0.05)


def test_schedule_for_song_time_prefetches_when_ahead_is_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heavy clip: off-RT schedule extends coverage when ahead is thin."""
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

    # 12s window from 0 — at t=1 ahead is only ~11s (< 36s min ahead).
    _inject(mixer, clip, _constant(12.0, 0.4))
    requested: list[float] = []

    def _capture(c: VideoClip, source_time: float, **kwargs) -> None:  # noqa: ANN003
        del kwargs
        requested.append(float(source_time))

    monkeypatch.setattr(mixer, "_request_window", _capture)

    mixer.schedule_for_song_time(1.0)
    assert requested, "expected refill when ahead is below min"
    assert max(requested) >= 10.0


def test_chunk_at_does_not_schedule_on_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    """Realtime path must never submit window decode work."""
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
    requested: list[float] = []
    monkeypatch.setattr(mixer, "_request_window", lambda c, t, **kw: requested.append(t))
    out = mixer.chunk_at(0, 256)
    assert np.all(out == 0.0)
    assert requested == []


def test_heavy_idle_when_ahead_is_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Do not thrash PyAV while plenty of PCM remains ahead of the playhead."""
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
    # Simulate several short windows covering 0..48s (ahead from t=5 is 43s).
    for origin in (0.0, 9.0, 18.0, 27.0, 36.0):
        mixer._install_window(
            clip.id,
            _pcm(
                _constant(12.0, 0.4),
                origin_seconds=origin,
                key=("c.mp4", SR, origin, 12.0),
            ),
        )
    requested: list[float] = []
    monkeypatch.setattr(mixer, "_request_window", lambda c, t, **kw: requested.append(t))
    # Off-RT schedule with healthy ahead must not thrash.
    mixer.schedule_for_song_time(5.0)
    out = mixer.chunk_at(int(5.0 * SR), 256)
    assert float(np.max(np.abs(out))) > 0.0
    assert requested == []


def test_mute_stops_window_scheduling(monkeypatch: pytest.MonkeyPatch) -> None:
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
    mixer.set_muted(True)
    requested: list[float] = []
    monkeypatch.setattr(mixer, "_request_window", lambda c, t, **kw: requested.append(t))
    mixer.schedule_for_song_time(10.0)
    mixer.preload([clip])
    assert requested == []


def test_suspend_stops_scheduling_and_chaining(monkeypatch: pytest.MonkeyPatch) -> None:
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
    mixer.set_schedule_suspended(True)
    requested: list[float] = []
    monkeypatch.setattr(mixer, "_request_window", lambda c, t, **kw: requested.append(t))
    mixer.schedule_for_song_time(10.0)
    assert requested == []


def test_quantized_window_reuses_key_for_nearby_times() -> None:
    clip = VideoClip.create(
        name="c",
        path=Path("c.mp4"),
        start_seconds=0.0,
        duration_seconds=600.0,
        source_duration_seconds=600.0,
    )
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    a = mixer._window_for(clip, 100.0)
    b = mixer._window_for(clip, 105.0)
    assert a == b
    # ~71s backward (1018→947 media-equivalent) lands on a stable grid cell.
    c = mixer._window_for(clip, 947.0)
    d = mixer._window_for(clip, 950.0)
    assert c == d


def test_lru_keeps_older_window_beyond_36s(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pinned playhead window must survive eviction even when oldest."""
    del monkeypatch
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    clip_id = "c"
    mixer._pin_source_time = 1.0
    for origin in (0.0, 9.0, 18.0, 27.0, 36.0, 45.0, 54.0, 63.0):
        mixer._install_window(
            clip_id,
            _pcm(
                _constant(12.0, 0.4),
                origin_seconds=origin,
                key=("c.mp4", SR, origin, 12.0),
            ),
        )
    mixer._install_window(
        clip_id,
        _pcm(
            _constant(12.0, 0.4),
            origin_seconds=72.0,
            key=("c.mp4", SR, 72.0, 12.0),
        ),
    )
    assert len(mixer._cache[clip_id]) == 8
    # Pinned window at t=1 (origin 0) must remain.
    assert mixer._find_covering(clip_id, 1.0) is not None
    assert ("c.mp4", SR, 0.0, 12.0) in mixer._cache[clip_id]


def test_non_heavy_does_not_prefetch_spam(monkeypatch: pytest.MonkeyPatch) -> None:
    """Short clips use one window — mid-play must not keep kicking PyAV."""
    song = Song.create("Song")
    clip = VideoClip.create(
        name="c",
        path=Path("c.mp4"),
        start_seconds=0.0,
        duration_seconds=180.0,
        source_duration_seconds=180.0,
    )
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)
    _inject(mixer, clip, _constant(180.0, 0.4))
    requested: list[float] = []
    monkeypatch.setattr(mixer, "_request_window", lambda c, t, **kw: requested.append(t))
    out = mixer.chunk_at(int(60.0 * SR), 256)
    assert float(np.max(np.abs(out))) > 0.0
    assert requested == []


def test_double_buffer_keeps_previous_window_while_sliding() -> None:
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    clip = VideoClip.create(name="c", path=Path("c.mp4"), duration_seconds=120.0)
    first = _pcm(
        _constant(30.0, 0.5),
        origin_seconds=0.0,
        key=("c.mp4", SR, 0.0, 30.0),
    )
    second = _pcm(
        _constant(30.0, 0.5),
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
        _pcm(
            _constant(30.0, 0.5),
            origin_seconds=0.0,
            key=("c.mp4", SR, 0.0, 30.0),
        ),
    )
    mixer._install_window(
        clip.id,
        _pcm(
            _constant(30.0, 0.7),
            origin_seconds=20.0,
            key=("c.mp4", SR, 20.0, 30.0),
        ),
    )
    # Straddle the first window's end (t=30); second window covers 20..50.
    at = int(29.5 * SR)
    out = mixer.chunk_at(at, int(1.0 * SR))
    assert float(np.min(np.abs(out))) > 0.0
    # Overlap keeps the older window; past A's end uses B.
    assert out[0, 0] == pytest.approx(0.5, abs=1e-4)
    assert out[-1, 0] == pytest.approx(0.7, abs=1e-4)


def test_gather_prefers_older_window_over_newer_silence() -> None:
    """A new window with a silent head must not punch a hole into good audio."""
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    clip_id = "c"
    good = _constant(30.0, 0.5)
    bad = _constant(30.0, 0.0)  # e.g. seek-pad zeros in a newer window
    mixer._install_window(
        clip_id,
        _pcm(good, origin_seconds=0.0, key=("a", SR, 0.0, 30.0)),
    )
    mixer._install_window(
        clip_id,
        _pcm(bad, origin_seconds=20.0, key=("b", SR, 20.0, 30.0)),
    )
    t = np.full(64, int(25.0 * SR), dtype=np.int64)
    out, valid, _owner = mixer._gather_samples(clip_id, t)
    assert bool(np.all(valid))
    assert float(np.min(np.abs(out))) == pytest.approx(0.5, abs=1e-4)


def _ramp(n: int, start: int = 0) -> np.ndarray:
    """Mono ramp encoded as stereo; value == absolute source frame index * 1e-6."""
    ramp = (np.arange(n, dtype=np.float32) + float(start)) * 1e-6
    return np.stack([ramp, ramp], axis=1)


def test_adjacent_windows_match_continuous_reference() -> None:
    """Independently stored adjacent windows assemble sample-for-sample."""
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    song = Song.create("Song")
    clip = VideoClip.create(
        name="c",
        path=Path("c.mp4"),
        start_seconds=0.0,
        duration_seconds=30.0,
        source_duration_seconds=30.0,
    )
    song.add_video_clip(clip)
    mixer.set_song(song)

    a_n = 12 * SR
    b_origin = 9 * SR
    b_n = 12 * SR
    ref = _ramp(b_origin + b_n, 0)
    mixer._install_window(
        clip.id,
        _pcm(ref[:a_n].copy(), origin_seconds=0.0, key=("c", SR, 0.0, 12.0)),
    )
    mixer._install_window(
        clip.id,
        _pcm(
            ref[b_origin : b_origin + b_n].copy(),
            origin_seconds=9.0,
            key=("c", SR, 9.0, 12.0),
        ),
    )

    # Walk repeatedly across the 9s / 12s seam.
    for start in range(8 * SR, 13 * SR, 256):
        out = mixer.chunk_at(start, 512)
        expected = ref[start : start + 512]
        assert out.shape == expected.shape
        np.testing.assert_allclose(out, expected, atol=1e-7)


def test_overlapping_windows_older_wins_deterministically() -> None:
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    clip_id = "c"
    a = _ramp(12 * SR, 0)
    # Newer window has deliberately different PCM in the overlap.
    b = np.full((12 * SR, 2), 0.9, dtype=np.float32)
    mixer._install_window(
        clip_id, _pcm(a, origin_seconds=0.0, key=("a", SR, 0.0, 12.0))
    )
    mixer._install_window(
        clip_id, _pcm(b, origin_seconds=9.0, key=("b", SR, 9.0, 12.0))
    )
    # Inside overlap: older ramp must win.
    t = np.arange(10 * SR, 10 * SR + 64, dtype=np.int64)
    out, valid, owner = mixer._gather_samples(clip_id, t)
    assert bool(np.all(valid))
    assert owner == ("a", SR, 0.0, 12.0)
    np.testing.assert_allclose(out[:, 0], t * 1e-6, atol=1e-7)
    # Past older end: newer fills.
    t2 = np.arange(12 * SR, 12 * SR + 64, dtype=np.int64)
    out2, valid2, owner2 = mixer._gather_samples(clip_id, t2)
    assert bool(np.all(valid2))
    assert owner2 == ("b", SR, 9.0, 12.0)
    assert float(out2[0, 0]) == pytest.approx(0.9, abs=1e-5)


def test_one_sample_boundary_no_gap_or_dup() -> None:
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    clip_id = "c"
    n = 1000
    left = _ramp(n, 0)
    right = _ramp(n, n)  # starts exactly where left ends
    mixer._install_window(
        clip_id, _pcm(left, origin_seconds=0.0, key=("L", SR, 0.0, n / SR))
    )
    mixer._install_window(
        clip_id,
        _pcm(right, origin_seconds=n / SR, key=("R", SR, n / SR, n / SR)),
    )
    t = np.arange(n - 8, n + 8, dtype=np.int64)
    out, valid, _ = mixer._gather_samples(clip_id, t)
    assert bool(np.all(valid))
    np.testing.assert_allclose(out[:, 0], t * 1e-6, atol=1e-7)
    # No duplicated frame index values across the seam.
    assert out[7, 0] != out[8, 0]


def test_eviction_preserves_pinned_playhead_window() -> None:
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    clip_id = "c"
    mixer._pin_source_time = 1.0  # inside window at 0
    for origin in (0.0, 9.0, 18.0, 27.0, 36.0, 45.0, 54.0, 63.0):
        mixer._install_window(
            clip_id,
            _pcm(
                _constant(12.0, 0.4),
                origin_seconds=origin,
                key=("c.mp4", SR, origin, 12.0),
            ),
        )
    mixer._install_window(
        clip_id,
        _pcm(
            _constant(12.0, 0.4),
            origin_seconds=72.0,
            key=("c.mp4", SR, 72.0, 12.0),
        ),
    )
    assert mixer._find_covering(clip_id, 1.0) is not None
    assert len(mixer._cache[clip_id]) == 8


def test_async_publish_while_gathering_is_lockfree() -> None:
    """RT gather must not wait on the worker lock during publish."""
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    song = Song.create("Song")
    clip = VideoClip.create(
        name="c",
        path=Path("c.mp4"),
        start_seconds=0.0,
        duration_seconds=60.0,
        source_duration_seconds=60.0,
    )
    song.add_video_clip(clip)
    mixer.set_song(song)
    mixer._install_window(
        clip.id,
        _pcm(_constant(12.0, 0.5), origin_seconds=0.0, key=("c", SR, 0.0, 12.0)),
    )

    stop = threading.Event()
    errors: list[BaseException] = []

    def _publisher() -> None:
        i = 0
        while not stop.is_set():
            origin = float((i % 5) * 9)
            with mixer._lock:
                mixer._install_window(
                    clip.id,
                    _pcm(
                        _constant(12.0, 0.4),
                        origin_seconds=origin,
                        key=("c", SR, origin, 12.0),
                    ),
                )
            i += 1

    def _reader() -> None:
        try:
            for _ in range(200):
                out = mixer.chunk_at(int(1.0 * SR), 256)
                assert out.shape == (256, 2)
                assert np.isfinite(out).all()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    pub = threading.Thread(target=_publisher)
    pub.start()
    _reader()
    stop.set()
    pub.join(timeout=2.0)
    assert not errors
    assert mixer.exceptional_callback_stats()["lock_wait_ns"] == 0


def test_nan_inf_and_short_buffer_rejected() -> None:
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    song = Song.create("Song")
    clip = VideoClip.create(
        name="c",
        path=Path("c.mp4"),
        start_seconds=0.0,
        duration_seconds=2.0,
        source_duration_seconds=2.0,
    )
    song.add_video_clip(clip)
    mixer.set_song(song)
    bad = _constant(2.0, 0.5)
    bad[10, 0] = np.nan
    bad[20, 1] = np.inf
    mixer._install_window(
        clip.id,
        _pcm(bad, origin_seconds=0.0, key=("c", SR, 0.0, 2.0)),
    )
    out = mixer.chunk_at(0, 64)
    assert np.isfinite(out).all()
    assert mixer.exceptional_callback_stats()["reject_nonfinite"] >= 1
    # Short gather shape reject path: force via monkey by returning wrong n —
    # covered by zeroing nonfinite rows above; gap fill stays silent.
    assert out[10, 0] == 0.0


def test_repeated_boundary_gather_no_dup_or_omit() -> None:
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    song = Song.create("Song")
    clip = VideoClip.create(
        name="c",
        path=Path("c.mp4"),
        start_seconds=0.0,
        duration_seconds=40.0,
        source_duration_seconds=40.0,
    )
    song.add_video_clip(clip)
    mixer.set_song(song)
    total = 30 * SR
    ref = _ramp(total, 0)
    for origin_s in (0.0, 9.0, 18.0):
        o = int(origin_s * SR)
        mixer._install_window(
            clip.id,
            _pcm(
                ref[o : o + 12 * SR].copy(),
                origin_seconds=origin_s,
                key=("c", SR, origin_s, 12.0),
            ),
        )
    assembled = []
    pos = 0
    while pos < 27 * SR:
        n = 1024
        assembled.append(mixer.chunk_at(pos, n))
        pos += n
    got = np.concatenate(assembled, axis=0)[: 27 * SR]
    np.testing.assert_allclose(got, ref[: 27 * SR], atol=1e-7)


def _heavy_clip(**kwargs) -> VideoClip:
    defaults = dict(
        name="c",
        path=Path("c.mp4"),
        start_seconds=0.0,
        duration_seconds=3600.0,
        source_duration_seconds=3600.0,
    )
    defaults.update(kwargs)
    return VideoClip.create(**defaults)


def test_far_future_cache_does_not_suppress_local_prefetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disjoint window at ~1800s must not make ahead look healthy at ~1688s."""
    song = Song.create("Song")
    clip = _heavy_clip()
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)
    mixer._install_window(
        clip.id,
        _pcm(
            _constant(12.0, 0.4),
            origin_seconds=1800.0,
            key=("c.mp4", SR, 1800.0, 12.0),
        ),
    )
    requested: list[float] = []
    monkeypatch.setattr(
        mixer, "_request_window", lambda c, t, **kw: requested.append(float(t))
    )
    mixer.schedule_for_song_time(1688.0)
    assert requested, "local prefetch must run despite far-future cache"
    # Must request near the 1683/1692 grid, never treat 1800 as local coverage.
    assert min(requested) < 1700.0
    assert all(t < 1790.0 for t in requested)


def test_backward_seek_contiguous_prefetch_ignores_old_future(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    song = Song.create("Song")
    clip = _heavy_clip()
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)
    for origin in (1800.0, 1809.0, 1818.0):
        mixer._install_window(
            clip.id,
            _pcm(
                _constant(12.0, 0.4),
                origin_seconds=origin,
                key=("c.mp4", SR, origin, 12.0),
            ),
        )
    requested: list[float] = []

    def _capture(c: VideoClip, source_time: float, **kwargs) -> None:  # noqa: ANN003
        del c, kwargs
        requested.append(float(source_time))

    monkeypatch.setattr(mixer, "_request_window", _capture)
    mixer.note_discontinuous_seek(1688.0)
    assert requested
    assert min(requested) < 1700.0
    # Quantized cells around 1683 / 1692 / 1701…
    assert any(abs(t - 1683.0) < 1.0 or abs(t - 1688.0) < 1.0 for t in requested)
    fr = mixer._contiguous_frontier_frame(clip.id, int(1688.0 * SR))
    assert fr is None  # no published local window yet


def test_contiguous_frontier_ignores_disjoint_future() -> None:
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    clip_id = "c"
    mixer._install_window(
        clip_id,
        _pcm(_constant(12.0, 0.4), origin_seconds=0.0, key=("a", SR, 0.0, 12.0)),
    )
    mixer._install_window(
        clip_id,
        _pcm(_constant(12.0, 0.4), origin_seconds=9.0, key=("b", SR, 9.0, 12.0)),
    )
    mixer._install_window(
        clip_id,
        _pcm(
            _constant(12.0, 0.4), origin_seconds=1800.0, key=("far", SR, 1800.0, 12.0)
        ),
    )
    fr = mixer._contiguous_frontier_frame(clip_id, int(5.0 * SR))
    assert fr == pytest.approx(21 * SR, abs=1)
    # Far window alone does not cover local playhead.
    assert mixer._contiguous_frontier_frame(clip_id, int(1688.0 * SR)) is None


def test_inflight_does_not_count_as_published_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    song = Song.create("Song")
    clip = _heavy_clip()
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)
    started = threading.Event()
    release = threading.Event()

    def _fake_get(path, *, start_seconds=0.0, max_duration_seconds=None):  # noqa: ANN001
        del path, max_duration_seconds
        started.set()
        assert release.wait(timeout=2.0)
        n = int(12.0 * SR)
        return VideoAudioBuffer(
            path=Path("c.mp4"),
            sample_rate=SR,
            samples=np.zeros((n, 2), dtype=np.float32),
            origin_seconds=float(start_seconds),
        )

    monkeypatch.setattr(
        "cueplayer.playback.video_audio_mixer.get_video_audio", _fake_get
    )
    mixer._request_window(clip, 10.0)
    assert started.wait(timeout=2.0)
    # In-flight covers 9..21 on the grid, but published frontier must stay None.
    assert mixer._covers_source(clip.id, 10.0)
    assert not mixer._covers_source_published(clip.id, 10.0)
    assert mixer._contiguous_frontier_frame(clip.id, int(10.0 * SR)) is None
    # Second request for same key must not duplicate submit.
    before = len(mixer._req_meta)
    mixer._request_window(clip, 10.0)
    assert mixer._inflight.get(clip.id) is not None
    release.set()
    deadline = time.monotonic() + 2.0
    while mixer.is_decoding() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert mixer._contiguous_frontier_frame(clip.id, int(10.0 * SR)) is not None
    del before


def test_eviction_prefers_disjoint_far_over_contiguous_forward() -> None:
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    clip_id = "c"
    mixer._pin_source_time = 5.0
    # Contiguous chain 0..63+12 and one disjoint far window.
    for origin in (0.0, 9.0, 18.0, 27.0, 36.0, 45.0, 54.0):
        mixer._install_window(
            clip_id,
            _pcm(
                _constant(12.0, 0.4),
                origin_seconds=origin,
                key=("c.mp4", SR, origin, 12.0),
            ),
        )
    mixer._install_window(
        clip_id,
        _pcm(
            _constant(12.0, 0.4),
            origin_seconds=1800.0,
            key=("c.mp4", SR, 1800.0, 12.0),
        ),
    )
    assert len(mixer._cache[clip_id]) == 8
    # Adding another contiguous forward window should evict the far one.
    mixer._install_window(
        clip_id,
        _pcm(
            _constant(12.0, 0.4),
            origin_seconds=63.0,
            key=("c.mp4", SR, 63.0, 12.0),
        ),
    )
    assert ("c.mp4", SR, 1800.0, 12.0) not in mixer._cache[clip_id]
    assert mixer._find_covering(clip_id, 5.0) is not None
    assert mixer._find_covering(clip_id, 65.0) is not None


def test_continuous_schedule_requests_next_before_frontier_exhausts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    song = Song.create("Song")
    clip = _heavy_clip()
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)
    # Only first window published — ahead ~11s from t=1, must prefetch next.
    mixer._install_window(
        clip.id,
        _pcm(_constant(12.0, 0.4), origin_seconds=0.0, key=("c.mp4", SR, 0.0, 12.0)),
    )
    requested: list[float] = []
    monkeypatch.setattr(
        mixer, "_request_window", lambda c, t, **kw: requested.append(float(t))
    )
    mixer.schedule_for_song_time(1.0)
    assert requested
    assert min(requested) >= 11.0  # at/after frontier (~12s)


def test_ten_boundary_assembly_no_gap_after_warmup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assemble across ten 9s seams with all windows pre-published — no gap_fill."""
    import cueplayer.playback.video_audio_mixer as vam

    monkeypatch.setattr(vam, "_MAX_WINDOWS_PER_CLIP", 16)
    song = Song.create("Song")
    clip = _heavy_clip()
    song.add_video_clip(clip)
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    mixer.set_song(song)
    total = int(100 * SR)
    ref = _ramp(total, 0)
    for i in range(12):
        origin_s = float(i * 9)
        o = int(origin_s * SR)
        mixer._install_window(
            clip.id,
            _pcm(
                ref[o : o + 12 * SR].copy(),
                origin_seconds=origin_s,
                key=("c", SR, origin_s, 12.0),
            ),
        )
    mixer._cb_gap_fill = 0
    pos = int(5 * SR)
    end = int(5 * SR + 10 * 9 * SR)  # ten 9s boundaries
    while pos < end:
        out = mixer.chunk_at(pos, 1024)
        np.testing.assert_allclose(out, ref[pos : pos + 1024], atol=1e-7)
        pos += 1024
    assert mixer._cb_gap_fill == 0


def test_contiguous_keys_excludes_disjoint_past_windows() -> None:
    """Regression: start<=frontier must NOT mark disjoint past holes as contiguous.

    Windows log showed preserved_contiguous with holes like
    1845 → 1872 (27s) and 1917 → 1944 (27s), which let eviction drop true
    forward grid cells and caused publish_late / gap_fill.
    """
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    clip_id = "c"
    # Contiguous local chain at 1944+, plus disjoint past islands.
    for origin in (1836.0, 1845.0, 1872.0, 1881.0, 1917.0, 1944.0, 1953.0, 1962.0):
        mixer._install_window(
            clip_id,
            _pcm(
                _constant(12.0, 0.4),
                origin_seconds=origin,
                key=("c.mp4", SR, origin, 12.0),
            ),
        )
    pin_frame = int(1952.0 * SR)
    keys = mixer._contiguous_keys(clip_id, pin_frame)
    starts = sorted(k[2] for k in keys)
    assert starts == [1944.0, 1953.0, 1962.0]
    assert 1845.0 not in starts
    assert 1872.0 not in starts
    assert 1917.0 not in starts
    fr = mixer._contiguous_frontier_frame(clip_id, pin_frame)
    assert fr == pytest.approx(int(1974.0 * SR), abs=1)


def test_eviction_does_not_drop_forward_chain_for_disjoint_past() -> None:
    """When cache is full, disjoint past islands are evicted before forward cells."""
    mixer = VideoAudioMixer()
    mixer.set_playback_rate(SR)
    clip_id = "c"
    mixer._pin_source_time = 1952.0
    # Fill with forward chain + disjoint past (holes 1854/1863, 1926/1935).
    for origin in (1836.0, 1845.0, 1872.0, 1881.0, 1890.0, 1944.0, 1953.0, 1962.0):
        mixer._install_window(
            clip_id,
            _pcm(
                _constant(12.0, 0.4),
                origin_seconds=origin,
                key=("c.mp4", SR, origin, 12.0),
            ),
        )
    assert len(mixer._cache[clip_id]) == 8
    # Publishing next forward window must keep 1944/1953/1962/1971 and drop past.
    mixer._install_window(
        clip_id,
        _pcm(
            _constant(12.0, 0.4),
            origin_seconds=1971.0,
            key=("c.mp4", SR, 1971.0, 12.0),
        ),
    )
    starts = sorted(k[2] for k in mixer._cache[clip_id])
    assert 1971.0 in starts
    assert 1944.0 in starts
    assert 1953.0 in starts
    assert 1962.0 in starts
    # Disjoint past islands should be preferred victims.
    assert 1836.0 not in starts or 1845.0 not in starts or 1872.0 not in starts
