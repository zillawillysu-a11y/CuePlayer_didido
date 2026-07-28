"""Video clip timeline edit math."""

from __future__ import annotations

import pytest

from cueplayer.ui.video_clip_edit import (
    clip_duration_after_right_trim,
    clip_start_after_body_drag,
    default_video_clip_duration,
)


def test_long_clip_can_move_past_song_end() -> None:
    # Song 60s, clip 120s — old logic pinned start at 0.
    assert clip_start_after_body_drag(0.0, 15.0) == 15.0
    assert clip_start_after_body_drag(5.0, 20.0) == 25.0


def test_clip_start_can_go_negative_with_deliberate_drag() -> None:
    # Parked at 0 — small nudge stays snapped.
    assert clip_start_after_body_drag(0.0, -0.05) == 0.0
    # Deliberate left drag escapes the snap well into pre-roll.
    assert clip_start_after_body_drag(0.0, -0.5) == pytest.approx(-0.5)
    assert clip_start_after_body_drag(-1.0, -0.5) == pytest.approx(-1.5)


def test_clip_start_snaps_to_zero_from_positive() -> None:
    assert clip_start_after_body_drag(2.0, -2.05) == 0.0


def test_clip_start_snaps_back_from_negative_pre_roll() -> None:
    assert clip_start_after_body_drag(-2.0, 1.95) == 0.0


def test_shift_disables_zero_snap() -> None:
    # Same small nudge that would stay parked at 0 — free with snap=False.
    assert clip_start_after_body_drag(0.0, -0.05, snap=False) == pytest.approx(-0.05)
    assert clip_start_after_body_drag(2.0, -2.05, snap=False) == pytest.approx(-0.05)
    assert clip_start_after_body_drag(-2.0, 1.95, snap=False) == pytest.approx(-0.05)


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
