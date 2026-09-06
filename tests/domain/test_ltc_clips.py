"""Per-song LTC clip domain tests (mapping, validation, mode rules)."""

from __future__ import annotations

from cueplayer.domain.ltc_clips import (
    add_ltc_clip,
    clip_at_position,
    ltc_clip_tc_range,
    ltc_timecode_at,
    remove_ltc_clip,
    resolved_song_ltc_source_mode,
    validate_ltc_clips,
)
from cueplayer.domain.models import Song


def _song(**overrides) -> Song:
    kwargs = dict(id="s1", name="測試歌", duration_seconds=100.0)
    kwargs.update(overrides)
    return Song(**kwargs)


# --- time mapping ---------------------------------------------------------


def test_clip_timecode_inside_advances_from_clip_start() -> None:
    song = _song()
    add_ltc_clip(
        song,
        timeline_start_seconds=10.0,
        duration_seconds=20.0,
        start_timecode="02:15:00:00",
    )
    # output_tc = clip.start_timecode + (position - clip.timeline_start)
    assert ltc_timecode_at(song.ltc_clips, 30.0, 10.0).format() == "02:15:00:00"
    assert ltc_timecode_at(song.ltc_clips, 30.0, 15.0).format() == "02:15:05:00"
    assert ltc_timecode_at(song.ltc_clips, 30.0, 29.966).format() == "02:15:19:29"


def test_no_timecode_outside_clips() -> None:
    song = _song()
    add_ltc_clip(
        song,
        timeline_start_seconds=10.0,
        duration_seconds=20.0,
        start_timecode="02:15:00:00",
    )
    assert ltc_timecode_at(song.ltc_clips, 30.0, 0.0) is None
    assert ltc_timecode_at(song.ltc_clips, 30.0, 9.999) is None
    assert ltc_timecode_at(song.ltc_clips, 30.0, 31.0) is None
    assert ltc_timecode_at(song.ltc_clips, 30.0, 99.0) is None


def test_last_clip_includes_its_end_point() -> None:
    song = _song()
    add_ltc_clip(
        song,
        timeline_start_seconds=80.0,
        duration_seconds=20.0,
        start_timecode="03:00:00:00",
    )
    assert ltc_timecode_at(song.ltc_clips, 30.0, 100.0).format() == "03:00:20:00"
    assert ltc_timecode_at(song.ltc_clips, 30.0, 100.001) is None


def test_boundary_between_adjacent_clips_belongs_to_later_clip() -> None:
    song = _song()
    add_ltc_clip(
        song,
        timeline_start_seconds=0.0,
        duration_seconds=50.0,
        start_timecode="01:00:00:00",
    )
    add_ltc_clip(
        song,
        timeline_start_seconds=50.0,
        duration_seconds=50.0,
        start_timecode="04:00:00:00",
    )
    # 49.966s → frame 1499 of clip 1; exactly 50.0 → clip 2 (jump).
    assert ltc_timecode_at(song.ltc_clips, 30.0, 49.966).format() == "01:00:49:29"
    assert ltc_timecode_at(song.ltc_clips, 30.0, 50.0).format() == "04:00:00:00"
    assert ltc_timecode_at(song.ltc_clips, 30.0, 50.5).format() == "04:00:00:15"


def test_gap_between_clips_has_no_timecode() -> None:
    song = _song()
    add_ltc_clip(
        song,
        timeline_start_seconds=0.0,
        duration_seconds=30.0,
        start_timecode="01:00:00:00",
    )
    add_ltc_clip(
        song,
        timeline_start_seconds=70.0,
        duration_seconds=30.0,
        start_timecode="05:00:00:00",
    )
    # Exactly 30.0 is clip 1's end point (its last boundary); just after is gap.
    assert ltc_timecode_at(song.ltc_clips, 30.0, 30.0).format() == "01:00:30:00"
    assert ltc_timecode_at(song.ltc_clips, 30.0, 30.001) is None
    assert ltc_timecode_at(song.ltc_clips, 30.0, 70.0).format() == "05:00:00:00"


def test_mapping_uses_song_fps_for_frames() -> None:
    song = _song()
    add_ltc_clip(
        song,
        timeline_start_seconds=0.0,
        duration_seconds=10.0,
        start_timecode="01:00:00:00",
    )
    # 1.979s at 24 fps = frame 47 (01:00:01:23); 0.48s at 25 fps = frame 12.
    assert ltc_timecode_at(song.ltc_clips, 24.0, 1.979).format() == "01:00:01:23"
    assert ltc_timecode_at(song.ltc_clips, 25.0, 0.48).format() == "01:00:00:12"


def test_clip_at_position_returns_none_for_empty_clips() -> None:
    song = _song()
    assert clip_at_position(song.ltc_clips, 5.0) is None


def test_invalid_clip_start_timecode_maps_to_none() -> None:
    song = _song()
    add_ltc_clip(
        song,
        timeline_start_seconds=0.0,
        duration_seconds=10.0,
        start_timecode="garbage",
    )
    assert ltc_timecode_at(song.ltc_clips, 30.0, 1.0) is None


# --- validation -----------------------------------------------------------


def test_validate_clean_clips_no_errors_no_warnings() -> None:
    song = _song(duration_seconds=100.0)
    add_ltc_clip(song, timeline_start_seconds=0.0, duration_seconds=40.0,
                 start_timecode="01:00:00:00")
    add_ltc_clip(song, timeline_start_seconds=40.0, duration_seconds=60.0,
                 start_timecode="01:05:00:00")
    errors, warnings = validate_ltc_clips(song.ltc_clips, 30.0, 100.0)
    assert errors == []
    assert warnings == []


def test_validate_flags_out_of_range_and_bad_clip() -> None:
    song = _song(duration_seconds=100.0)
    add_ltc_clip(song, timeline_start_seconds=-1.0, duration_seconds=10.0,
                 start_timecode="01:00:00:00")
    add_ltc_clip(song, timeline_start_seconds=95.0, duration_seconds=10.0,
                 start_timecode="01:00:00:00")
    add_ltc_clip(song, timeline_start_seconds=0.0, duration_seconds=0.0,
                 start_timecode="01:00:00:00")
    add_ltc_clip(song, timeline_start_seconds=10.0, duration_seconds=5.0,
                 start_timecode="99:99:99:99")
    errors, _ = validate_ltc_clips(song.ltc_clips, 30.0, 100.0)
    assert len(errors) == 4
    assert any("before 0:00" in e for e in errors)
    assert any("ends after song end" in e for e in errors)
    assert any("duration must be > 0" in e for e in errors)
    assert any("invalid start timecode" in e for e in errors)


def test_validate_warns_on_timeline_overlap() -> None:
    song = _song(duration_seconds=100.0)
    add_ltc_clip(song, timeline_start_seconds=0.0, duration_seconds=40.0,
                 start_timecode="01:00:00:00")
    add_ltc_clip(song, timeline_start_seconds=30.0, duration_seconds=40.0,
                 start_timecode="01:10:00:00")
    _, warnings = validate_ltc_clips(song.ltc_clips, 30.0, 100.0)
    assert any("overlap on the timeline" in w for w in warnings)


def test_validate_warns_on_overlapping_tc_range() -> None:
    # Clip A emits 01:00:00:00–01:05:00:00; clip B starts inside that range.
    song = _song(duration_seconds=200.0)
    add_ltc_clip(song, timeline_start_seconds=0.0, duration_seconds=300.0,
                 start_timecode="01:00:00:00")
    add_ltc_clip(song, timeline_start_seconds=310.0, duration_seconds=60.0,
                 start_timecode="01:03:00:00")
    # (song duration is long enough for both clips to be in range)
    _, warnings = validate_ltc_clips(song.ltc_clips, 30.0, 400.0)
    assert any("overlapping or backwards TC ranges" in w for w in warnings)


def test_validate_warns_on_backwards_tc_jump() -> None:
    # Later clip starts at a TC earlier than the earlier clip's start.
    song = _song(duration_seconds=200.0)
    add_ltc_clip(song, timeline_start_seconds=0.0, duration_seconds=50.0,
                 start_timecode="02:00:00:00")
    add_ltc_clip(song, timeline_start_seconds=60.0, duration_seconds=50.0,
                 start_timecode="01:00:00:00")
    _, warnings = validate_ltc_clips(song.ltc_clips, 30.0, 200.0)
    assert any("overlapping or backwards TC ranges" in w for w in warnings)


def test_clip_tc_range_end_is_exclusive_after_full_duration() -> None:
    song = _song()
    clip = add_ltc_clip(
        song,
        timeline_start_seconds=0.0,
        duration_seconds=10.0,
        start_timecode="01:00:00:00",
    )
    rng = ltc_clip_tc_range(clip, 30.0)
    assert rng is not None
    assert rng.start_tc.format() == "01:00:00:00"
    assert rng.end_tc.format() == "01:00:10:00"
    assert rng.end_frames - rng.start_frames == 300


# --- mode rules (mutual exclusion) ----------------------------------------


def test_first_clip_switches_mode_to_clip_generator() -> None:
    for prior in ("auto", "full_track_generator", "striped_file", "off"):
        song = _song(ltc_source_mode=prior)
        clip = add_ltc_clip(
            song,
            timeline_start_seconds=0.0,
            duration_seconds=10.0,
            start_timecode="01:00:00:00",
        )
        assert song.ltc_source_mode == "clip_generator"
        assert song.ltc_clips == [clip]


def test_add_keeps_clips_sorted_by_start() -> None:
    song = _song()
    add_ltc_clip(song, timeline_start_seconds=50.0, duration_seconds=10.0,
                 start_timecode="01:00:00:00")
    add_ltc_clip(song, timeline_start_seconds=10.0, duration_seconds=10.0,
                 start_timecode="01:05:00:00")
    add_ltc_clip(song, timeline_start_seconds=30.0, duration_seconds=10.0,
                 start_timecode="01:10:00:00")
    starts = [c.timeline_start_seconds for c in song.ltc_clips]
    assert starts == [10.0, 30.0, 50.0]


def test_removing_last_clip_keeps_clip_generator() -> None:
    song = _song()
    clip = add_ltc_clip(
        song,
        timeline_start_seconds=0.0,
        duration_seconds=10.0,
        start_timecode="01:00:00:00",
    )
    assert remove_ltc_clip(song, clip.id) is True
    assert song.ltc_clips == []
    # Never auto-restores full_track_generator.
    assert song.ltc_source_mode == "clip_generator"
    assert remove_ltc_clip(song, clip.id) is False


def test_empty_clip_generator_outputs_no_timecode() -> None:
    song = _song(ltc_source_mode="clip_generator")
    assert ltc_timecode_at(song.ltc_clips, 30.0, 5.0) is None


# --- legacy auto resolution ------------------------------------------------


def test_explicit_modes_win_over_project_settings() -> None:
    for mode in ("striped_file", "full_track_generator", "clip_generator", "off"):
        song = _song(ltc_source_mode=mode)
        assert (
            resolved_song_ltc_source_mode(
                song, project_ltc_source="generator", ltc_enabled=True
            )
            == mode
        )


def test_auto_resolves_like_legacy_project_settings() -> None:
    song = _song(ltc_source_mode="auto")
    assert (
        resolved_song_ltc_source_mode(song, project_ltc_source="generator")
        == "full_track_generator"
    )
    assert (
        resolved_song_ltc_source_mode(song, project_ltc_source="auto")
        == "striped_file"
    )
    assert (
        resolved_song_ltc_source_mode(song, project_ltc_source="source_left")
        == "striped_file"
    )
    assert (
        resolved_song_ltc_source_mode(song, project_ltc_source="generator",
                                      ltc_enabled=False)
        == "off"
    )
