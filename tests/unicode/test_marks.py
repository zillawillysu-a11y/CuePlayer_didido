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


def test_last_mark_at_or_before_follows_chronological_playhead() -> None:
    song = Project.create("測試").songs[0]
    main = song.add_mark(1, 1.0, "Main")
    song.add_mark(2, 2.5, "Hit")
    song.add_mark(1, 4.0, "Main2")

    assert song.last_mark_at_or_before(0.5) is None
    assert song.last_mark_at_or_before(1.0).id == main.id
    assert song.last_mark_at_or_before(3.0).display_name == "Hit"
    assert song.last_mark_at_or_before(5.0).display_name == "Main2"


def test_last_cue_list_mark_skips_disabled_lanes() -> None:
    song = Project.create("測試").songs[0]
    main = song.add_mark(1, 1.0, "Main")
    song.add_mark(2, 2.0, "Skip")
    main2 = song.add_mark(1, 3.0, "Main2")
    lane2 = song.lane_by_index(2)
    assert lane2 is not None
    lane2.cue_list_enabled = False

    assert song.last_cue_list_mark_at_or_before(2.5).id == main.id
    assert song.last_cue_list_mark_at_or_before(3.5).id == main2.id
    # Chronological helper still sees the non-list lane.
    assert song.last_mark_at_or_before(2.5).display_name == "Skip"
