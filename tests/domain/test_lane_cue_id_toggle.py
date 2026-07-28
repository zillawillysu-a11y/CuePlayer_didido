"""Per-lane Cue ID vs Button assignment."""

from __future__ import annotations

from cueplayer.domain.main_cue_id import assign_main_cue_id_for_mark, sync_lane_cue_ids
from cueplayer.domain.models import Song
from cueplayer.persistence.project_store import project_from_dict, project_to_dict


def test_button_lane_can_get_cue_id_when_enabled() -> None:
    song = Song.create("Test")
    button = next(lane for lane in song.mark_lanes if not lane.cue_id_enabled)
    button.cue_id_enabled = True
    button.lane_type = "main"
    mark = song.add_mark(button.index, 1.0)
    assert mark.main_cue_id == "1"


def test_disabling_cue_id_clears_numbers() -> None:
    song = Song.create("Test")
    main = next(lane for lane in song.mark_lanes if lane.cue_id_enabled)
    mark = song.add_mark(main.index, 1.0)
    assert mark.main_cue_id == "1"
    main.cue_id_enabled = False
    main.lane_type = "top_button"
    sync_lane_cue_ids(song)
    assert mark.main_cue_id == ""


def test_cue_ids_are_per_lane_not_global() -> None:
    song = Song.create("Test")
    lane_a = next(lane for lane in song.mark_lanes if lane.cue_id_enabled)
    lane_b = next(lane for lane in song.mark_lanes if not lane.cue_id_enabled)
    lane_b.cue_id_enabled = True
    lane_b.lane_type = "main"
    mark_a = song.add_mark(lane_a.index, 1.0)
    mark_b = song.add_mark(lane_b.index, 2.0)
    assert mark_a.main_cue_id == "1"
    assert mark_b.main_cue_id == "1"


def test_cue_id_enabled_persists() -> None:
    song = Song.create("Test")
    song.mark_lanes[1].cue_id_enabled = True
    from cueplayer.domain.models import Project

    project = Project.create("p")
    project.songs = [song]
    data = project_to_dict(project)
    loaded = project_from_dict(data)
    assert loaded.songs[0].mark_lanes[1].cue_id_enabled is True
