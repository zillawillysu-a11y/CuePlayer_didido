"""Mark Manager template save / load / apply."""

from __future__ import annotations

from pathlib import Path

from cueplayer.domain.models import Mark, MarkLane, Project, Song
from cueplayer.persistence.mark_template import (
    apply_lanes_to_song,
    build_template,
    dicts_to_lanes,
    load_mark_template,
    save_mark_template,
)


def _sample_lanes() -> list[MarkLane]:
    return [
        MarkLane(index=1, name="Go", lane_type="main", color="#E74C3C", shortcut="1"),
        MarkLane(
            index=2,
            name="Spot",
            lane_type="top_button",
            color="#3498DB",
            shortcut="2",
            marker_shape="diamond",
        ),
    ]


def test_template_roundtrip(tmp_path: Path) -> None:
    lanes = _sample_lanes()
    path = tmp_path / "show.cueplayer-marks.json"
    template = build_template(
        lanes,
        name="show",
        now_primary_lanes=[1],
        now_secondary_lanes=[2],
    )
    save_mark_template(path, template)
    loaded = load_mark_template(path)
    assert loaded["kind"] == "cueplayer.mark_template"
    restored = dicts_to_lanes(loaded["mark_lanes"])
    assert len(restored) == 2
    assert restored[0].name == "Go"
    assert restored[1].marker_shape == "diamond"
    assert loaded["now_primary_lanes"] == [1]


def test_apply_drops_orphan_marks() -> None:
    song = Song.create("A")
    song.marks = [
        Mark.create(1, 1.0, "keep"),
        Mark.create(5, 2.0, "drop"),
    ]
    dropped = apply_lanes_to_song(song, _sample_lanes())
    assert dropped == 1
    assert len(song.marks) == 1
    assert song.marks[0].lane_index == 1
    assert [lane.name for lane in song.mark_lanes] == ["Go", "Spot"]


def test_project_new_song_uses_default() -> None:
    project = Project.create("Show")
    project.default_mark_lanes = _sample_lanes()
    song = project.new_song("Intro")
    assert [lane.name for lane in song.mark_lanes] == ["Go", "Spot"]
    # Clone, not shared reference
    song.mark_lanes[0].name = "Changed"
    assert project.default_mark_lanes[0].name == "Go"
