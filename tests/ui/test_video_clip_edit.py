"""Video clip timeline edit math."""

from __future__ import annotations

import pytest

from cueplayer.ui.video_clip_edit import (
    clip_duration_after_right_trim,
    clip_start_after_body_drag,
    default_video_clip_duration,
    split_video_clip_transforms,
)


def test_long_clip_can_move_past_song_end() -> None:
    assert clip_start_after_body_drag(0.0, 15.0) == 15.0
    assert clip_start_after_body_drag(5.0, 20.0) == 25.0


def test_body_drag_clamps_at_zero_no_pre_roll() -> None:
    # Moving the clip body must never go negative — clamp is a hard wall,
    # not a soft/escapable snap.
    assert clip_start_after_body_drag(10.0, -20.0) == 0.0
    assert clip_start_after_body_drag(0.0, -5.0) == 0.0
    assert clip_start_after_body_drag(0.0, -0.01) == 0.0


def test_right_trim_not_capped_by_song_duration() -> None:
    # 60s song, clip at 50s with 20s duration — extend 30s more (past song end).
    new_dur = clip_duration_after_right_trim(
        20.0,
        30.0,
        source_in_seconds=0.0,
        source_duration_seconds=120.0,
    )
    assert new_dur == 50.0


def test_right_trim_still_respects_source_media() -> None:
    new_dur = clip_duration_after_right_trim(
        10.0,
        100.0,
        source_in_seconds=5.0,
        source_duration_seconds=30.0,
    )
    assert new_dur == 25.0  # 30 - 5


def test_default_add_duration_fits_song() -> None:
    assert default_video_clip_duration(300.0, 180.0, 10.0) == 170.0
    assert default_video_clip_duration(60.0, 180.0, 10.0) == 60.0


def test_split_basic() -> None:
    # TEST S1: timeline_start=10, source_in=5, duration=20, playhead=18
    result = split_video_clip_transforms(10.0, 5.0, 20.0, 18.0)
    assert result is not None
    left_duration, right_source_in, right_duration = result
    assert left_duration == pytest.approx(8.0)
    assert right_source_in == pytest.approx(13.0)
    assert right_duration == pytest.approx(12.0)


def test_split_source_continuity() -> None:
    # TEST S2: LEFT source end == RIGHT source start for the worked example
    # from the task spec (timeline_start=100, source_in=20, duration=60, playhead=125).
    result = split_video_clip_transforms(100.0, 20.0, 60.0, 125.0)
    assert result is not None
    left_duration, right_source_in, right_duration = result
    left_source_end = 20.0 + left_duration
    assert left_source_end == pytest.approx(right_source_in)
    assert left_duration == pytest.approx(25.0)
    assert right_source_in == pytest.approx(45.0)
    assert right_duration == pytest.approx(35.0)


def test_split_invalid_boundaries_are_no_op() -> None:
    # TEST S3: playhead at clip start / clip end / inside the minimum-duration
    # floor must all be a no-op (None), never a crash or a degenerate clip.
    assert split_video_clip_transforms(10.0, 0.0, 20.0, 10.0) is None
    assert split_video_clip_transforms(10.0, 0.0, 20.0, 30.0) is None
    assert split_video_clip_transforms(10.0, 0.0, 20.0, 10.02) is None
    assert split_video_clip_transforms(10.0, 0.0, 20.0, 29.98) is None


def test_split_exactly_at_minimum_duration_is_allowed() -> None:
    result = split_video_clip_transforms(10.0, 0.0, 20.0, 10.05)
    assert result is not None
    assert result[0] == pytest.approx(0.05)
