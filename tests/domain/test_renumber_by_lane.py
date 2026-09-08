"""Renumber Cue IDs by Cue List lane scope."""

from __future__ import annotations

from cueplayer.domain.main_cue_id import (
    capture_main_cue_ids,
    renumber_main_cue_ids_sequential,
    renumberable_cue_list_lanes,
)
from cueplayer.domain.models import Song


def test_renumberable_cue_list_lanes_skips_button_and_disabled() -> None:
    song = Song.create("Test")
    main = next(lane for lane in song.mark_lanes if lane.cue_id_enabled)
    button = next(lane for lane in song.mark_lanes if not lane.cue_id_enabled)
    song.add_mark(main.index, 1.0)
    song.add_mark(button.index, 2.0)

    assert [lane.index for lane in renumberable_cue_list_lanes(song)] == [main.index]

    main.cue_list_enabled = False
    assert renumberable_cue_list_lanes(song) == []


def test_renumber_all_cue_list_lanes() -> None:
    song = Song.create("Test")
    main = next(lane for lane in song.mark_lanes if lane.cue_id_enabled)
    song.add_mark(main.index, 1.0)
    song.add_mark(main.index, 2.0)
    inserted = song.add_mark(main.index, 1.5)
    assert inserted.main_cue_id == "1.1"

    after = renumber_main_cue_ids_sequential(song)
    assert [m.main_cue_id for m in song.main_marks_sorted()] == ["1", "2", "3"]
    assert after == {m.id: m.main_cue_id for m in song.main_marks_sorted()}


def test_renumber_single_lane_scope() -> None:
    song = Song.create("Test")
    main = next(lane for lane in song.mark_lanes if lane.cue_id_enabled)
    song.add_mark(main.index, 1.0)
    song.add_mark(main.index, 2.0)
    song.marks[1].main_cue_id = "9"

    scope = {main.index}
    before = capture_main_cue_ids(song, lane_indices=scope)
    after = renumber_main_cue_ids_sequential(song, lane_indices=scope)
    assert before != after
    assert [m.main_cue_id for m in song.main_marks_sorted()] == ["1", "2"]


def test_renumber_ignores_button_lane_marks() -> None:
    song = Song.create("Test")
    main = next(lane for lane in song.mark_lanes if lane.cue_id_enabled)
    button = next(lane for lane in song.mark_lanes if not lane.cue_id_enabled)
    button.cue_list_enabled = True
    song.add_mark(main.index, 1.0)
    song.add_mark(button.index, 2.0)

    renumber_main_cue_ids_sequential(song)
    main_mark = song.main_marks_sorted()[0]
    button_mark = next(m for m in song.marks if m.lane_index == button.index)
    assert main_mark.main_cue_id == "1"
    assert button_mark.main_cue_id == ""
