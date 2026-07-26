"""Basic timeline marking behavior tests (no GUI event loop required)."""

from __future__ import annotations

from cueplayer.domain.models import Project


def test_add_marks_on_lanes_sorted_by_time() -> None:
    song = Project.create("測試").songs[0]
    song.add_mark(1, 3.0)
    song.add_mark(2, 1.5)
    song.add_mark(1, 2.0)
    assert [m.time_seconds for m in song.marks] == [1.5, 2.0, 3.0]
    assert len(song.marks_for_lane(1)) == 2
    assert song.lane_by_index(1).lane_type == "main"
