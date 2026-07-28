"""Tests for fractional Main Cue ID assignment."""

from __future__ import annotations

import pytest

from cueplayer.domain.main_cue_id import (
    assign_main_cue_id_for_mark,
    between_main_cue_ids,
    next_main_cue_id_at_end,
)
from cueplayer.domain.models import Mark, Song


def test_between_user_examples() -> None:
    assert between_main_cue_ids("1", "2") == "1.1"
    assert between_main_cue_ids("1.1", "2") == "1.2"
    assert between_main_cue_ids("1", "1.1") == "1.01"


def test_next_at_end() -> None:
    assert next_main_cue_id_at_end([]) == "1"
    assert next_main_cue_id_at_end(["1"]) == "2"
    assert next_main_cue_id_at_end(["1", "1.1", "2"]) == "3"


def test_add_main_marks_sequential() -> None:
    song = Song.create("Test")
    main_lane = song.lane_by_index(1)
    assert main_lane is not None
    assert main_lane.lane_type == "main"

    first = song.add_mark(1, 1.0)
    second = song.add_mark(1, 2.0)
    third = song.add_mark(1, 3.0)
    assert first.main_cue_id == "1"
    assert second.main_cue_id == "2"
    assert third.main_cue_id == "3"


def test_insert_between_1_and_2_preserves_existing_ids() -> None:
    song = Song.create("Test")
    m1 = song.add_mark(1, 1.0)
    m2 = song.add_mark(1, 2.0)
    m3 = song.add_mark(1, 3.0)
    inserted = song.add_mark(1, 1.5)
    assert inserted.main_cue_id == "1.1"
    assert [m.main_cue_id for m in song.main_marks_sorted()] == ["1", "1.1", "2", "3"]
    assert m1.main_cue_id == "1"
    assert m2.main_cue_id == "2"
    assert m3.main_cue_id == "3"


def test_refresh_main_cue_ids_does_not_renumber_existing() -> None:
    from cueplayer.domain.main_cue_id import refresh_main_cue_ids

    song = Song.create("Test")
    m1 = song.add_mark(1, 1.0)
    m2 = song.add_mark(1, 2.0)
    m3 = song.add_mark(1, 3.0)
    inserted = song.add_mark(1, 1.5)
    refresh_main_cue_ids(song)
    assert [m.main_cue_id for m in song.main_marks_sorted()] == ["1", "1.1", "2", "3"]
    refresh_main_cue_ids(song, mark_ids={inserted.id})
    assert m1.main_cue_id == "1"
    assert m2.main_cue_id == "2"
    assert m3.main_cue_id == "3"


def test_insert_main_mark_between_integers() -> None:
    song = Song.create("Test")
    song.add_mark(1, 1.0)
    song.add_mark(1, 3.0)
    inserted = song.add_mark(1, 2.0)
    assert inserted.main_cue_id == "1.1"
    ordered = song.main_marks_sorted()
    assert [m.main_cue_id for m in ordered] == ["1", "1.1", "2"]


def test_insert_deeper_between_one_and_one_one() -> None:
    song = Song.create("Test")
    song.add_mark(1, 1.0)
    song.add_mark(1, 3.0)
    song.add_mark(1, 2.0)
    deep = song.add_mark(1, 1.5)
    assert deep.main_cue_id == "1.01"
    ordered = song.main_marks_sorted()
    assert [m.main_cue_id for m in ordered] == ["1", "1.01", "1.1", "2"]


def test_button_lane_has_no_main_cue_id() -> None:
    song = Song.create("Test")
    button_lane = next(lane for lane in song.mark_lanes if lane.lane_type == "top_button")
    mark = song.add_mark(button_lane.index, 1.0)
    assert mark.main_cue_id == ""


def test_assign_main_cue_id_for_mark_after_move() -> None:
    song = Song.create("Test")
    a = song.add_mark(1, 1.0)
    b = song.add_mark(1, 2.0)
    c = song.add_mark(1, 3.0)
    assert [m.main_cue_id for m in song.main_marks_sorted()] == ["1", "2", "3"]
    c.time_seconds = 1.5
    song.sort_marks()
    assign_main_cue_id_for_mark(song, c, force=True)
    assert c.main_cue_id == "1.1"
    assert a.main_cue_id == "1"
    assert b.main_cue_id == "2"


def test_between_invalid_bounds_raises() -> None:
    with pytest.raises(ValueError):
        between_main_cue_ids("2", "1")
