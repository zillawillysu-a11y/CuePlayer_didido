"""VideoAudioMixer: pure frame-math tests (no real file decode — the cache is
injected directly so these stay fast and independent of media/test_video_audio_loader.py).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cueplayer.domain.models import Song, VideoClip
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
    mixer._cache[clip.id] = _CachedPcm(
        samples=samples, origin_seconds=origin, key=key
    )


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
