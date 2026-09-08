"""Mark lane height is project-global, not per song."""

from __future__ import annotations

import json
from pathlib import Path

from cueplayer.domain.models import Project
from cueplayer.persistence.project_store import load_project, save_project


def test_mark_lane_height_persists_on_project(tmp_path: Path) -> None:
    project = Project.create("Show")
    project.mark_lane_height = 48.0
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.mark_lane_height == 48.0


def test_mark_lane_height_legacy_song_only(tmp_path: Path) -> None:
    project = Project.create("Show")
    path = tmp_path / "legacy.cueplayer.json"
    save_project(project, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("mark_lane_height", None)
    data["songs"][0]["mark_lane_height"] = 40.0
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_project(path)
    assert loaded.mark_lane_height == 40.0
