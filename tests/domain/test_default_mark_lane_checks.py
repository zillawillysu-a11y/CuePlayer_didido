"""Default Mark Manager checkbox pattern for new songs / projects."""

from __future__ import annotations

from cueplayer.domain.models import Project, Song


def test_default_mark_lane_checkbox_pattern() -> None:
    song = Song.create("Untitled Song")
    assert len(song.mark_lanes) == 9

    main = song.lane_by_index(1)
    assert main is not None
    assert main.name == "Main"
    assert main.visible is True
    assert main.cue_list_enabled is True
    assert main.cue_id_enabled is True
    assert main.midi_note_enabled is False
    assert main.marker_shape == "triangle_up"
    assert song.now_primary_lanes == [1]
    assert song.now_secondary_lanes == list(range(2, 10))

    for index in range(2, 10):
        lane = song.lane_by_index(index)
        assert lane is not None
        assert lane.visible is True
        assert lane.cue_list_enabled is True
        assert lane.cue_id_enabled is False
        assert lane.midi_note_enabled is True
        assert lane.marker_shape == "triangle_up"


def test_project_create_uses_same_mark_defaults() -> None:
    project = Project.create("Show")
    song = project.songs[0]
    assert song.lane_by_index(1).cue_id_enabled is True
    assert song.lane_by_index(1).midi_note_enabled is False
    assert song.lane_by_index(2).cue_list_enabled is True
    assert song.lane_by_index(2).midi_note_enabled is True
    assert project.waveform_color == "#616161"
    assert song.waveform_color == "#616161"
    assert project.playhead_color == "#3dd68c"
