"""Mark track row tint is project-global."""

from __future__ import annotations

import json
from pathlib import Path

from cueplayer.domain.models import Project
from cueplayer.persistence.project_store import load_project, save_project


def test_show_mark_track_colors_persists_on_project(tmp_path: Path) -> None:
    project = Project.create("Show")
    project.show_mark_track_colors = False
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.show_mark_track_colors is False


def test_show_mark_track_colors_migrates_from_lane_flags(tmp_path: Path) -> None:
    project = Project.create("Show")
    project.songs[0].mark_lanes[0].show_row_color = False
    path = tmp_path / "legacy.cueplayer.json"
    save_project(project, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("show_mark_track_colors", None)
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_project(path)
    assert loaded.show_mark_track_colors is False
