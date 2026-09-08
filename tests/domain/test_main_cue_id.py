"""Tests for fractional Main Cue ID assignment."""

from __future__ import annotations

import pytest

from cueplayer.domain.main_cue_id import (
    assign_main_cue_id_for_mark,
    between_main_cue_ids,
    is_valid_main_cue_id_text,
    main_cue_id_fits_order,
    main_cue_id_taken,
    next_main_cue_id_at_end,
    normalize_main_cue_id_text,
)
from cueplayer.domain.models import Mark, Song


def test_between_user_examples() -> None:
    assert between_main_cue_ids("1", "2") == "1.1"
    assert between_main_cue_ids("1.1", "2") == "1.2"
    assert between_main_cue_ids("1", "1.1") == "1.01"
    assert between_main_cue_ids("27", "29") == "28"
    assert between_main_cue_ids("27", "29", avoid={"28"}) == "27.1"


def test_drag_28_between_26_and_27_becomes_26_1() -> None:
    song = Song.create("Test")
    m26 = song.add_mark(1, 1.0)
    m27 = song.add_mark(1, 2.0)
    m28 = song.add_mark(1, 3.0)
    m29 = song.add_mark(1, 4.0)
    m26.main_cue_id = "26"
    m27.main_cue_id = "27"
    m28.main_cue_id = "28"
    m29.main_cue_id = "29"
    m28.time_seconds = 1.5
    song.sort_marks()
    assign_main_cue_id_for_mark(song, m28, force=True)
    assert m28.main_cue_id == "26.1"
    assert m26.main_cue_id == "26"
    assert m27.main_cue_id == "27"


def test_drag_26_1_between_27_and_29_reclaims_28() -> None:
    song = Song.create("Test")
    m26 = song.add_mark(1, 1.0)
    m27 = song.add_mark(1, 2.0)
    m28 = song.add_mark(1, 3.0)
    m29 = song.add_mark(1, 4.0)
    m26.main_cue_id = "26"
    m27.main_cue_id = "27"
    m28.main_cue_id = "28"
    m29.main_cue_id = "29"
    m28.time_seconds = 1.5
    song.sort_marks()
    assign_main_cue_id_for_mark(song, m28, force=True)
    assert m28.main_cue_id == "26.1"
    m28.time_seconds = 2.5
    song.sort_marks()
    assign_main_cue_id_for_mark(song, m28, force=True)
    assert m28.main_cue_id == "28"
    assert [m.main_cue_id for m in song.main_marks_sorted()] == ["26", "27", "28", "29"]


def test_insert_between_27_and_29_uses_vacant_28() -> None:
    song = Song.create("Test")
    a = song.add_mark(1, 1.0)
    b = song.add_mark(1, 2.0)
    c = song.add_mark(1, 4.0)
    a.main_cue_id = "26"
    b.main_cue_id = "27"
    c.main_cue_id = "29"
    inserted = song.add_mark(1, 3.0)
    assign_main_cue_id_for_mark(song, inserted, force=True)
    assert inserted.main_cue_id == "28"


def test_next_at_end() -> None:
    assert next_main_cue_id_at_end([]) == "1"
    assert next_main_cue_id_at_end(["1"]) == "2"
    assert next_main_cue_id_at_end(["1", "1.1", "2"]) == "3"


def test_same_time_marks_list_in_cue_id_order() -> None:
    """Cue List must not show 7 then 6 when two Main cues share a timestamp."""
    song = Song.create("Test")
    for i in range(5):
        song.add_mark(1, float(i))
    earlier = song.add_mark(1, 10.0)
    later = song.add_mark(1, 11.0)
    assert earlier.main_cue_id == "6"
    assert later.main_cue_id == "7"
    # Drag 6 onto 7's time — stable time-only sort used to leave 7 before 6.
    earlier.time_seconds = later.time_seconds
    song.sort_marks()
    ids = [m.main_cue_id for m in song.marks if abs(m.time_seconds - 11.0) < 1e-9]
    assert ids == ["6", "7"]


def test_second_mark_at_same_time_gets_next_integer() -> None:
    song = Song.create("Test")
    for i in range(5):
        song.add_mark(1, float(i))
    first = song.add_mark(1, 53.306)
    second = song.add_mark(1, 53.306)
    assert first.main_cue_id == "6"
    assert second.main_cue_id == "7"
    assert [m.main_cue_id for m in song.marks if abs(m.time_seconds - 53.306) < 1e-9] == [
        "6",
        "7",
    ]


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


def test_drag_integer_keeps_id_when_still_between_neighbors() -> None:
    song = Song.create("Test")
    a = song.add_mark(1, 1.0)
    b = song.add_mark(1, 2.0)
    c = song.add_mark(1, 3.0)
    # Drag cue 2 later in time but still between 1 and 3.
    b.time_seconds = 2.5
    song.sort_marks()
    assign_main_cue_id_for_mark(song, b, force=True)
    assert [m.main_cue_id for m in song.main_marks_sorted()] == ["1", "2", "3"]


def test_drag_to_end_keeps_high_integer_id() -> None:
    song = Song.create("Test")
    song.add_mark(1, 1.0)
    song.add_mark(1, 2.0)
    c = song.add_mark(1, 3.0)
    c.time_seconds = 4.0
    song.sort_marks()
    assign_main_cue_id_for_mark(song, c, force=True)
    assert c.main_cue_id == "3"


def test_between_invalid_bounds_raises() -> None:
    with pytest.raises(ValueError):
        between_main_cue_ids("2", "1")


def test_manual_cue_id_validation() -> None:
    assert is_valid_main_cue_id_text("1.1")
    assert is_valid_main_cue_id_text("2")
    assert not is_valid_main_cue_id_text("")
    assert not is_valid_main_cue_id_text("abc")
    assert normalize_main_cue_id_text(" 1.10 ") == "1.1"


def test_main_cue_id_taken() -> None:
    song = Song.create("Test")
    first = song.add_mark(1, 1.0)
    song.add_mark(1, 2.0)
    assert main_cue_id_taken(song, "1", exclude_mark_id=first.id, lane_index=1) is False
    assert main_cue_id_taken(song, "2", exclude_mark_id=first.id, lane_index=1) is True


def test_manual_cue_id_must_increase_in_time_order() -> None:
    song = Song.create("Test")
    first = song.add_mark(1, 1.0)
    second = song.add_mark(1, 2.0)
    song.add_mark(1, 4.0)
    between = song.add_mark(1, 3.0)
    assert second.main_cue_id == "2"
    assert between.main_cue_id == "2.1"
    assert main_cue_id_fits_order(song, second.id, "2.05") is True
    assert main_cue_id_fits_order(song, second.id, "3") is False
    assert main_cue_id_fits_order(song, between.id, "3") is False
    assert main_cue_id_fits_order(song, first.id, "0.5") is True

