import pytest

from cueplayer.domain.models import BeatGridRegion, Project
from cueplayer.persistence.project_store import project_from_dict, project_to_dict
from cueplayer.domain.undo import (
    BeatGridSnapshot,
    DeleteBeatGridCommand,
    EditBeatGridCommand,
    MoveBeatGridCommand,
    ResizeBeatGridCommand,
)


def test_beat_grid_math_and_round_trip() -> None:
    project = Project.create("節拍測試")
    song = project.songs[0]
    grid = BeatGridRegion.create(
        1.25,
        9.25,
        bpm=120.0,
        beats_per_bar=3,
        beat_unit=4,
        subdivision=2,
        color="#abcdef",
        locked=True,
    )
    song.beat_grids.append(grid)
    project.beat_grid_color = "#123456"
    project.beat_grid_line_style = "solid"
    project.show_beat_grid = False

    assert grid.beat_seconds == 0.5
    assert grid.step_seconds == 0.25

    loaded = project_from_dict(project_to_dict(project))
    restored = loaded.songs[0].beat_grids[0]
    assert loaded.beat_grid_color == "#123456"
    assert loaded.beat_grid_line_style == "solid"
    assert loaded.show_beat_grid is False
    assert restored.start_seconds == 1.25
    assert restored.end_seconds == 9.25
    assert restored.bpm == 120.0
    assert restored.beats_per_bar == 3
    assert restored.beat_unit == 4
    assert restored.subdivision == 2
    assert restored.color == "#abcdef"
    assert restored.locked is True


def test_old_project_without_beat_grid_fields_uses_defaults() -> None:
    data = project_to_dict(Project.create("Old"))
    data.pop("beat_grid_color")
    data.pop("beat_grid_line_style")
    data.pop("show_beat_grid")
    data["songs"][0].pop("beat_grids")

    loaded = project_from_dict(data)

    assert loaded.beat_grid_color == "#4c8bf5"
    assert loaded.beat_grid_line_style == "dash"
    assert loaded.show_beat_grid is True
    assert loaded.songs[0].beat_grids == []


def test_delete_beat_grid_command_undo_and_redo_preserve_all_settings() -> None:
    project = Project.create("Undo grid")
    song = project.songs[0]
    grid = BeatGridRegion.create(
        1.25, 9.75, bpm=137.5, beats_per_bar=3, beat_unit=8, subdivision=4,
        color="#fedcba",
    )
    song.beat_grids.append(grid)
    command = DeleteBeatGridCommand(grid=BeatGridSnapshot.from_grid(grid))

    command.redo(song)
    assert song.beat_grids == []

    command.undo(song)
    restored = song.beat_grids[0]
    assert restored == grid
    assert restored.color == "#fedcba"

    command.redo(song)
    assert song.beat_grids == []


def test_move_beat_grid_command_undo_and_redo_preserve_duration() -> None:
    song = Project.create("Move grid").songs[0]
    grid = BeatGridRegion.create(1.25, 9.75, bpm=137.5)
    song.beat_grids.append(grid)
    command = MoveBeatGridCommand(grid.id, old_start=1.25, new_start=3.0)

    command.redo(song)
    assert (grid.start_seconds, grid.end_seconds) == pytest.approx((3.0, 11.5))
    command.undo(song)
    assert (grid.start_seconds, grid.end_seconds) == pytest.approx((1.25, 9.75))


def test_edit_beat_grid_command_undoes_color_and_all_settings() -> None:
    song = Project.create("Edit grid").songs[0]
    grid = BeatGridRegion.create(1.0, 5.0, bpm=120.0, color="#112233")
    song.beat_grids.append(grid)
    before = BeatGridSnapshot.from_grid(grid)
    grid.end_seconds = 7.0
    grid.bpm = 95.0
    grid.beats_per_bar = 3
    grid.beat_unit = 8
    grid.subdivision = 2
    grid.color = "#abcdef"
    grid.locked = True
    after = BeatGridSnapshot.from_grid(grid)
    command = EditBeatGridCommand(old_grid=before, new_grid=after)

    command.undo(song)
    assert BeatGridSnapshot.from_grid(grid) == before
    command.redo(song)
    assert BeatGridSnapshot.from_grid(grid) == after


def test_resize_beat_grid_command_undo_and_redo() -> None:
    song = Project.create("Resize grid").songs[0]
    grid = BeatGridRegion.create(1.0, 9.0, bpm=120.0)
    song.beat_grids.append(grid)
    command = ResizeBeatGridCommand(grid.id, 1.0, 9.0, 2.0, 12.0)

    command.redo(song)
    assert (grid.start_seconds, grid.end_seconds) == pytest.approx((2.0, 12.0))
    command.undo(song)
    assert (grid.start_seconds, grid.end_seconds) == pytest.approx((1.0, 9.0))
