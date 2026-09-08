"""Track-header add-Mark safety switch is project-global and defaults off."""

from __future__ import annotations

import json
from pathlib import Path

from cueplayer.domain.models import Project
from cueplayer.persistence.project_store import load_project, save_project


def test_mark_lane_header_add_defaults_off() -> None:
    assert Project.create("Safe default").mark_lane_header_add_enabled is False


def test_mark_lane_header_add_persists(tmp_path: Path) -> None:
    project = Project.create("Enabled")
    project.mark_lane_header_add_enabled = True
    path = tmp_path / "enabled.cueplayer.json"
    save_project(project, path)

    assert load_project(path).mark_lane_header_add_enabled is True


def test_legacy_project_without_switch_defaults_off(tmp_path: Path) -> None:
    project = Project.create("Legacy")
    path = tmp_path / "legacy.cueplayer.json"
    save_project(project, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("mark_lane_header_add_enabled", None)
    path.write_text(json.dumps(data), encoding="utf-8")

    assert load_project(path).mark_lane_header_add_enabled is False
