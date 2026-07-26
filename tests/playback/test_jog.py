"""Tests for the Left/Right arrow-key hold acceleration curve."""

from __future__ import annotations

from cueplayer.playback.jog import hold_step_frames


def test_fresh_tap_is_exactly_one_frame() -> None:
    assert hold_step_frames(0.0) == 1
    assert hold_step_frames(-1.0) == 1


def test_step_size_increases_monotonically_with_hold_time() -> None:
    samples = [0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 10.0]
    steps = [hold_step_frames(t) for t in samples]
    for prev, nxt in zip(steps, steps[1:]):
        assert nxt >= prev


def test_ramps_up_to_a_visibly_faster_scrub_before_max_hold() -> None:
    # Somewhere in the middle of the ramp it should already be well beyond
    # a single frame per tick, without having to wait for the full ramp.
    mid = hold_step_frames(2.0, ramp_seconds=4.0)
    assert 1 < mid < 30


def test_reaches_and_stays_pegged_at_max_frames() -> None:
    at_ramp_end = hold_step_frames(4.0, ramp_seconds=4.0, max_frames=30)
    long_hold = hold_step_frames(60.0, ramp_seconds=4.0, max_frames=30)
    assert at_ramp_end == 30
    assert long_hold == 30


def test_custom_bounds_are_respected() -> None:
    assert hold_step_frames(0.0, min_frames=2) == 2
    assert hold_step_frames(100.0, max_frames=5) == 5


def test_zero_or_negative_ramp_holds_at_min_frames() -> None:
    assert hold_step_frames(2.0, ramp_seconds=0.0) == 1
    assert hold_step_frames(2.0, ramp_seconds=-1.0) == 1
