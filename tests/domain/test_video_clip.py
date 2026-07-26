"""Domain-level VideoClip / Song helpers: creation, geometry, overlap, active-clip lookup."""

from __future__ import annotations

from pathlib import Path

import pytest

from cueplayer.domain.models import Song, VideoClip


def test_video_clip_create_sets_end_and_source_out() -> None:
    clip = VideoClip.create(
        name="開場影片",
        path=Path("中文資料夾/開場.mp4"),
        start_seconds=2.0,
        source_in_seconds=1.0,
        duration_seconds=4.0,
    )
    assert clip.duration_seconds == 4.0
    assert clip.end_seconds == 6.0
    assert clip.source_out_seconds == 5.0
    assert clip.path == Path("中文資料夾/開場.mp4")


def test_video_clip_create_clamps_degenerate_values() -> None:
    clip = VideoClip.create(name="x", path=Path("x.mp4"), start_seconds=-5.0, duration_seconds=0.0)
    assert clip.start_seconds == 0.0
    assert clip.duration_seconds >= 0.02  # never a zero/negative-length clip


def test_video_clip_default_volume_is_unity() -> None:
    """Default audible at full volume — see AGENTS.md non-negotiable: video
    must play its own audio for picture/sound alignment work."""
    clip = VideoClip.create(name="x", path=Path("x.mp4"))
    assert clip.volume == 1.0


def test_video_clip_create_clamps_volume_to_0_1() -> None:
    loud = VideoClip.create(name="x", path=Path("x.mp4"), volume=2.5)
    quiet = VideoClip.create(name="x", path=Path("x.mp4"), volume=-1.0)
    assert loud.volume == 1.0
    assert quiet.volume == 0.0


def test_song_video_track_muted_defaults_false() -> None:
    """Audible by default: alignment work needs to hear the video clip
    against the music (explicit user request overriding the deferred
    OBS-reference "video audio muted by default" assumption)."""
    song = Song.create("Song")
    assert song.video_track_muted is False


def test_video_clip_contains_is_half_open() -> None:
    clip = VideoClip.create(name="x", path=Path("x.mp4"), start_seconds=1.0, duration_seconds=2.0)
    assert clip.contains(1.0) is True
    assert clip.contains(2.5) is True
    assert clip.contains(3.0) is False  # end boundary excluded
    assert clip.contains(0.999) is False


def test_video_clip_source_time_for_maps_timeline_to_source() -> None:
    clip = VideoClip.create(
        name="x", path=Path("x.mp4"), start_seconds=10.0, source_in_seconds=3.0, duration_seconds=5.0
    )
    assert clip.source_time_for(10.0) == 3.0
    assert clip.source_time_for(12.5) == 5.5
    # Before the clip start: never goes backward past source_in.
    assert clip.source_time_for(5.0) == 3.0


def test_song_add_video_clip_keeps_sorted_by_start() -> None:
    song = Song.create("Song")
    late = VideoClip.create(name="late", path=Path("a.mp4"), start_seconds=10.0, duration_seconds=2.0)
    early = VideoClip.create(name="early", path=Path("b.mp4"), start_seconds=1.0, duration_seconds=2.0)
    song.add_video_clip(late)
    song.add_video_clip(early)
    assert [c.name for c in song.video_clips] == ["early", "late"]


def test_song_video_clip_by_id_roundtrip() -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="x", path=Path("x.mp4"))
    song.add_video_clip(clip)
    assert song.video_clip_by_id(clip.id) is clip
    assert song.video_clip_by_id("missing-id") is None


def test_song_remove_video_clips_by_ids() -> None:
    song = Song.create("Song")
    a = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=2.0)
    b = VideoClip.create(name="b", path=Path("b.mp4"), start_seconds=5.0, duration_seconds=2.0)
    song.add_video_clip(a)
    song.add_video_clip(b)
    removed = song.remove_video_clips_by_ids({a.id})
    assert removed == 1
    assert [c.id for c in song.video_clips] == [b.id]


def test_song_overlapping_video_clip_ids() -> None:
    song = Song.create("Song")
    a = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=5.0)
    b = VideoClip.create(name="b", path=Path("b.mp4"), start_seconds=3.0, duration_seconds=5.0)
    c = VideoClip.create(name="c", path=Path("c.mp4"), start_seconds=20.0, duration_seconds=2.0)
    song.add_video_clip(a)
    song.add_video_clip(b)
    song.add_video_clip(c)
    overlapping = song.overlapping_video_clip_ids()
    assert overlapping == {a.id, b.id}


def test_song_overlapping_video_clip_ids_empty_when_no_overlap() -> None:
    song = Song.create("Song")
    a = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=2.0)
    b = VideoClip.create(name="b", path=Path("b.mp4"), start_seconds=2.0, duration_seconds=2.0)
    song.add_video_clip(a)
    song.add_video_clip(b)
    assert song.overlapping_video_clip_ids() == set()


def test_video_clip_source_time_for_loops_when_stretched_past_source_span() -> None:
    clip = VideoClip.create(
        name="x",
        path=Path("x.mp4"),
        start_seconds=0.0,
        source_in_seconds=0.0,
        duration_seconds=10.0,
        media_kind="video",
    )
    clip.source_out_seconds = 4.0
    assert clip.source_time_for(0.0) == 0.0
    assert clip.source_time_for(3.9) == pytest.approx(3.9)
    assert clip.source_time_for(4.0) == pytest.approx(0.0)
    assert clip.source_time_for(6.0) == pytest.approx(2.0)


def test_video_clip_source_time_for_still_is_constant() -> None:
    clip = VideoClip.create(
        name="logo",
        path=Path("logo.png"),
        start_seconds=2.0,
        duration_seconds=5.0,
        media_kind="still",
    )
    assert clip.source_time_for(2.0) == 0.0
    assert clip.source_time_for(6.5) == 0.0


def test_video_clip_crossfade_weights_across_overlap() -> None:
    from cueplayer.domain.models import video_clip_crossfade_weight

    a = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=5.0)
    b = VideoClip.create(name="b", path=Path("b.mp4"), start_seconds=3.0, duration_seconds=5.0)
    clips = [a, b]
    assert video_clip_crossfade_weight(a, 2.5, clips) == pytest.approx(1.0)
    assert video_clip_crossfade_weight(b, 2.5, clips) == pytest.approx(0.0)
    assert video_clip_crossfade_weight(a, 3.0, clips) == pytest.approx(1.0)
    assert video_clip_crossfade_weight(b, 3.0, clips) == pytest.approx(0.0)
    assert video_clip_crossfade_weight(a, 4.0, clips) == pytest.approx(0.5)
    assert video_clip_crossfade_weight(b, 4.0, clips) == pytest.approx(0.5)
    assert video_clip_crossfade_weight(a, 5.0, clips) == pytest.approx(0.0)
    assert video_clip_crossfade_weight(b, 5.0, clips) == pytest.approx(1.0)


def test_song_active_video_clip_at_prefers_later_clip_mid_crossfade() -> None:
    song = Song.create("Song")
    a = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=5.0)
    b = VideoClip.create(name="b", path=Path("b.mp4"), start_seconds=3.0, duration_seconds=5.0)
    song.add_video_clip(a)
    song.add_video_clip(b)
    active = song.active_video_clip_at(4.0)
    assert active is not None
    assert active.id == b.id


def test_song_active_video_clip_at_skips_hidden_clips() -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="hidden", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=5.0)
    clip.hidden = True
    song.add_video_clip(clip)
    assert song.active_video_clip_at(1.0) is None


def test_song_active_video_clip_at_none_when_no_clip_covers_time() -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=10.0, duration_seconds=2.0)
    song.add_video_clip(clip)
    assert song.active_video_clip_at(0.0) is None
    assert song.active_video_clip_at(50.0) is None
